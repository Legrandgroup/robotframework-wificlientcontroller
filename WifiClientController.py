#!/usr/bin/python
# -*- coding: utf-8 -*-

__author__    = 'Nicolas Gillen <nicolas.gillen@legrand.fr>'

import os
import sys
import re
import threading
import time
import argparse
import subprocess

sys.path.insert(0, '/opt/python-local/usr/local/lib/python2.7/dist-packages/')
import wpactrl

progname = os.path.basename(sys.argv[0])

class ScannedNetwork:
	"""
	This class is used to store scanned network informations
	"""
	def __init__(self, bssid, frequency, signal_level, flags, ssid):
		self._bssid = bssid
		self._frequency = frequency
		self._signal_level = signal_level
		self._flags = flags
		self._ssid = ssid
		
	def __repr__(self):
		return "bssid: " + self._bssid + "\nfrequency: " + self._frequency + "\nsignal level: " + self._signal_level + "\nflags: " + self._flags + "\nssid: " + self._ssid
	
	__srt__ = __repr__
	
	def getBssid(self):
		return self._bssid
	
	def getFrequency(self):
		return self._frequency
	
	def getSignalLevel(self):
		return self._signal_level
	
	def getFlags(self):
		return self._flags
	
	def getSsid(self):
		return self._ssid

class WifiClientController:
	
	""" Robot Framework Wi-Fi Library """

	ROBOT_LIBRARY_DOC_FORMAT = 'ROBOT'
	ROBOT_LIBRARY_SCOPE = 'GLOBAL'
	ROBOT_LIBRARY_VERSION = '1.0'
	
	DEFAULT_WPA_SUPPLICANT_SOCKET_PATH = '/var/run/wpa_supplicant/'
	def __init__(self, wpa_supplicant_socket_path=None, ifname='wlan0'):
		if wpa_supplicant_socket_path is None:
			self._wpa_supplicant_socket_path = WifiClientController.DEFAULT_WPA_SUPPLICANT_SOCKET_PATH
		else:
			self._wpa_supplicant_socket_path = wpa_supplicant_socket_path
		
		self._ifname = ifname
		self._socket = None
		self._wpa = None
		self._wifi_event_listener = None
		self._thread_quit_event = None
		self._event_status = None
		self._thread_disconnected_event = None
		self._is_connected = None
		
	def _event_listener(self):
		"""
		Thread that listen Wi-Fi event on socket
		It updates self._event_status variable continuously. When a disconnection is detected while not expected, it raises an exception.
		This thread quit when event self._thread_quit_event is set.
		"""

		wpa_event = wpactrl.WPACtrl(self._socket)
		wpa_event.attach()
		while not self._thread_quit_event.isSet():
			while wpa_event.pending():
				message = wpa_event.recv()
				logger.debug(message)
				status = re.findall(r"^<\d>CTRL-EVENT-([A-Z]+).*$", message)
				if len(status) > 0:
					self._event_status = status[0]
					if self._thread_disconnected_event.isSet() and self._event_status == 'DISCONNECTED':
						self._is_connected = False
						logger.debug('Unexpected disconnection')
		self._thread_quit_event = None
		self._event_status = None
		wpa_event.detach()

	def start(self):
		"""
		Start Wi-Fi Client Controller
		
		Example:
		| Start |
		"""
		# Set directory owner
		cmd = ['sudo', 'chgrp', '-R', 'jenkins', str(self._wpa_supplicant_socket_path)]
		subprocess.check_call(cmd, stdout=open(os.devnull, 'wb'), stderr=subprocess.STDOUT)
		
		# Make wireless interface up
		cmd = ['sudo', 'ifconfig', str(self._ifname), 'up']
		subprocess.check_call(cmd, stdout=open(os.devnull, 'wb'), stderr=subprocess.STDOUT)
		
		if self._wpa_supplicant_socket_path[-1] != '/':
			self._socket = self._wpa_supplicant_socket_path + '/' + self._ifname
		else:
			self._socket = self._wpa_supplicant_socket_path + self._ifname
		
		if not os.path.exists(self._socket): # Check if the socket exists
			raise Exception(self._socket + ' doesn\'t exists')

		self._wpa = wpactrl.WPACtrl(self._socket)

		self._thread_quit_event = threading.Event()
		self._thread_disconnected_event = threading.Event()
		self._wifi_event_listener = threading.Thread(target = self._event_listener)
		self._wifi_event_listener.setDaemon(True)
		self._wifi_event_listener.start()

		self._wpa.request('REMOVE_NETWORK all') # Clear all networks
		self._is_connected = False

		logger.debug('WiFi Client Controller started on %s' % self._socket)

	def stop(self):
		"""
		Stop Wi-Fi Client Controller
		
		Example:
		| Stop |
		"""
		self._thread_quit_event.set()
		self._wifi_event_listener = None
		self._thread_disconnected_event = None
		
		self._wpa.request('REMOVE_NETWORK all') # Clear all networks
		
		self._socket = None
		self._wpa = None

		# Set directory owner
		cmd = ['sudo', 'chown', '-R', 'root:root', str(self._wpa_supplicant_socket_path)]
		subprocess.call(cmd, stdout=open(os.devnull, 'wb'), stderr=subprocess.STDOUT)
		
		logger.debug('WiFi Client Controller stopped')
		
	def restart(self):
		"""
		Restart Wi-Fi Client Controller
		
		Example:
		| Restart |
		"""
		self.stop()
		self.start()

	def scan(self):
		"""
		Scan available Wi-Fi networks
		This function returns a list of ScannedNetwork object.
		Each member of ScannedNetwork can be got by using appropriate ScannedNetwork method
		
		Example:
		| Scan |
		=>
		| ${detected_networks} |
		"""
		self._wpa.request('SCAN')
		scan_raw=self._wpa.request('SCAN_RESULTS')
		# bssid - frequency - signal level - flags - ssid
		scan = re.findall(r"^([0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2})\s+(\d{4})\s+(-\d+)\s+(\S+)\s+(\S+).*$", scan_raw, re.MULTILINE)

		scanned_network_list = []
		for net in scan:
			scanned_network_list.append(ScannedNetwork(*net))

		return scanned_network_list
		
	def connect(self, ssid, encryption, key=None):
		"""
		Connect to a Wi-Fi network
		This function the network id that is created an connected
		
		Example:
		| Connect | 'ssid' | 'NONE' or 'WPA' or 'WPA2' or 'WPA-WPA2' | 'key' | 
		=>
		| ${network_id}
		"""
		network_id = self._wpa.request('ADD_NETWORK').splitlines()[0] # Fisrt line returned contains created network id
		self._wpa.request('SET_NETWORK %d ssid "%s"' % (int(network_id), ssid))
		
		if encryption == 'NONE':
			self._wpa.request('SET_NETWORK %d key_mgmt %s' % (int(network_id), encryption))
		elif encryption == 'WPA':
			if key == None:
				raise Exception('No key provided')
			self._wpa.request('SET_NETWORK %d key_mgmt WPA-PSK' % int(network_id))
			self._wpa.request('SET_NETWORK %d psk "%s"' % (int(network_id), key))
		elif encryption == 'WPA2':
			if key == None:
				raise Exception('No key provided')
			self._wpa.request('SET_NETWORK %d key_mgmt WPA-PSK' % int(network_id))
			self._wpa.request('SET_NETWORK %d proto RSN' % int(network_id))
			self._wpa.request('SET_NETWORK %d psk "%s"' % (int(network_id), key))
		elif encryption == 'WPA-WPA2':
			if key == None:
				raise Exception('No key provided')
			self._wpa.request('SET_NETWORK %d key_mgmt WPA-PSK' % int(network_id))
			self._wpa.request('SET_NETWORK %d pairwise CCMP TKIP' % int(network_id))
			self._wpa.request('SET_NETWORK %d group CCMP TKIP' % int(network_id))
		else:
			raise Exception('Unknown encryption method ' + encryption)
		
		self._wpa.request('SELECT_NETWORK %d' % int(network_id))
		self._wpa.request('ENABLE_NETWORK %d' % int(network_id))

		timeout = 10	# Connection timeout set to 10 seconds
		while self._event_status != 'CONNECTED':
			time.sleep(1)
			timeout -= 1
			if timeout <= 0:
				raise Exception('Can\'t connect to ssid "' + str(ssid) + '"')

		self._thread_disconnected_event.set()
		self._is_connected = True
		logger.debug('Connected to ssid %s' % ssid)
		
		return network_id
	
	def disconnect(self, network_id):
		"""
		Disconnect a Wi-Fi network
		
		Example:
		| Disconnect | 'network_id' |
		"""
		self._wpa.request('DISABLE_NETWORK %d' % int(network_id))
		self._thread_disconnected_event.clear()

		timeout = 4	# Disconnection timeout set to 4 seconds
		while self._event_status != 'DISCONNECTED':
			time.sleep(0.5)
			timeout -= 0.5
			if timeout <= 0:
				raise Exception('Can\'t disconnect from network ' + str(network_id))
			
		self._is_connected = False
		logger.debug('Disconnected from network %d' % int(network_id))
		
	def is_connected(self):
		"""
		Give connection status
		Return True if Wi-Fi is connected, False otherwise
		
		Example:
		| Is Connected |
		=>
		| True or False |
		"""
		return self._is_connected
	
	def check_connection(self):
		"""
		Check connection status
		Returns nothing if everything is OK and raise an exception if connection has been unexpectedly lost
		
		Example:
		| Check Connection |
		"""
		if self._thread_disconnected_event.isSet() and self._is_connected == False:
			raise Exception('Connection lost')

if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="This program control wpa_supplicant daemon.", prog=progname)
	parser.add_argument('-s', '--socketdir', type=str, help='path to directory where wpa_sipplicant stores sockets')
	parser.add_argument('-i', '--ifname', type=str, help='wireless network interface to control', required=True)

	args = parser.parse_args()
	
	try:
		from console_logger import LOGGER as logger
	except ImportError:
		import logging

		logger = logging.getLogger('WifiClientController_logger')
		logger.setLevel(logging.DEBUG)
		
		handler = logging.StreamHandler()
		handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
		logger.addHandler(handler)

	wifiController = WifiClientController(wpa_supplicant_socket_path = args.socketdir, ifname = args.ifname)
	wifiController.start()
	nid = wifiController.connect(ssid='mirabox', encryption='NONE')
	time.sleep(10)
	print wifiController.is_connected()
	time.sleep(10)
	wifiController.check_connection()
	wifiController.disconnect(nid)
	#wifiController.scan()
	wifiController.stop()
else:
	from robot.api import logger

