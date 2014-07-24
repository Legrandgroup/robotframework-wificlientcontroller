#!/usr/bin/python
# -*- coding: utf-8 -*-

__author__    = 'Nicolas Gillen <nicolas.gillen@legrand.fr>'

import os
import sys
import re
import threading
import subprocess

#from robot.libraries.BuiltIn import BuiltIn	# Import BuiltIn to interact with RF

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
	
	def to_string_list(self):
		return ['bssid: ' + self._bssid,
		        'frequency: ' + self._frequency,
		        'signal level: ' + self._signal_level,
		        'flags: ' + self._flags,
		        'ssid: "' + self._ssid + '"']
	
	def __repr__(self):
		return '\n'.join(self.to_string_list())
	
	def __str__(self):
		return ' '.join(self.to_string_list())
	
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
	
	def __init__(self, wpa_supplicant_socket_path=None, ifname=None):
		if wpa_supplicant_socket_path is None:
			self._wpa_supplicant_socket_path = WifiClientController.DEFAULT_WPA_SUPPLICANT_SOCKET_PATH
		else:
			self._wpa_supplicant_socket_path = wpa_supplicant_socket_path
		
		self._ifname = ifname
		self._socket = None
		self._wpa = None
		self._wifi_event_listener_thread = None
		self._thread_quit_event = None	# Thread event. When set, will force self._wifi_event_listener_thread (that runs self._event_listener()) to terminate
		
		# self._thread_keep_connection is a boolean variable, when set to True, will force self._event_listener() to watch for any unexpected Wi-Fi disconnection and set self._unexpected_disconnection=True if this happens
		self._thread_keep_connection = False
		self._unexpected_disconnection = False
		
		self._thread_disconnected_event = None	# Thread event. Will be set by self._event_listener() when a Wi-Fi disconnection event happens
		self._thread_connected_event = None	# Thread event. Will be set by self._event_listener() when a Wi-Fi connection event happens
		
	def _event_listener(self):
		"""
		Thread that listen Wi-Fi event on socket
		Handles connection and disconnection events from the socket
		This thread quit when event self._thread_quit_event is set.
		This thread will set self._thread_disconnected_event and self._thread_connected_event when respective Wi-Fi events happen
		If self._thread_keep_connection is True, this thread will watch for any Wi-Fi disconnection and set self._unexpected_disconnection=True if this happens
		"""

		wpa_event = wpactrl.WPACtrl(self._socket)
		wpa_event.attach()
		while not self._thread_quit_event.isSet():
			while wpa_event.pending():
				message = wpa_event.recv()
				logger.debug(message)
				status = re.findall(r"^<\d>CTRL-EVENT-([A-Z]+).*$", message)
				if len(status) > 0:
					event_status = status[0]
					if event_status == 'DISCONNECTED':
						self._thread_disconnected_event.set()
						if self._thread_keep_connection:
							logger.debug('Unexpected disconnection')
							self._unexpected_disconnection = True
							#BuiltIn().fail('Unexpected disconnection')
					elif event_status == 'CONNECTED':
						self._thread_connected_event.set()
					
		self._thread_quit_event = None
		wpa_event.detach()

	def set_interface(self, ifname):
		"""Set the interface on which the WifiClientController will act
		This must be done prior to calling Start on the WifiClientController object
		
		Example:
		| Set Interface | 'wlan0' |
		"""
		
		if not self._socket is None or not self._wpa is None:
		    raise Exception('Controller already started')
		
		self._ifname = ifname
		
	def get_interface(self, ifname):
		"""Get the interface on which the WifiClientController is configured to run (it may not be started yet)
		Will return None if no interface has been configured yet
		
		Example:
		| Set Interface | 'wlan0' |
		| Get Interface |
		=>
		| 'wlan0' |
		"""
		
		return self._ifname
		
	def start(self):
		"""
		Start Wi-Fi Client Controller
		
		Example:
		| Start |
		"""
		if self._ifname is None:	# self._iface may be None if it has not been provided at construction, in that case, a call to set_interface() is mandatory before calling start()
			raise Exception('No Wi-Fi interface setup')
		
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
		self._thread_connected_event = threading.Event()

		self._unexpected_disconnection = False
		self._thread_keep_connection = False
		
		self._wifi_event_listener_thread = threading.Thread(target = self._event_listener)
		self._wifi_event_listener_thread.setDaemon(True)
		self._wifi_event_listener_thread.start()
		
		self._wpa.request('REMOVE_NETWORK all') # Clear all networks
		
		logger.debug('WiFi Client Controller started on %s' % self._socket)
	
	def stop(self):
		"""
		Stop Wi-Fi Client Controller
		
		Example:
		| Stop |
		"""
		self._thread_quit_event.set()	# self._thread_quit_event will be automatically set to None in thread self._wifi_event_listener_thread
		self._wifi_event_listener_thread.join()
		self._wifi_event_listener_thread = None	# Destroy reference to thread
		self._thread_disconnected_event = None
		self._thread_connected_event = None

		self._unexpected_disconnection = False
		self._thread_keep_connection = False
		
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
		
	def log_scanned_networks(self):
		""" Scan available Wi-Fi networks and dump them to the logger
		
		Example:
		| Log Scanned Networks |
		"""
		
		network_list = self.scan()
		for net in network_list:
			logger.info(str(net))
		
	def connect(self, ssid, encryption, key=None, timeout = 10):
		"""
		Connect to a Wi-Fi network
		This function the network id that is created an connected
		timeout (optional) specifies the maximum time allowed (in seconds) to connect to the wireless network before failing
		
		Example:
		| Connect | 'ssid' | 'NONE' or 'WPA' or 'WPA2' or 'WPA-WPA2' | 'key' | 10 |
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
		
		self._unexpected_disconnection = False
		
		self._thread_connected_event.clear()
		self._wpa.request('SELECT_NETWORK %d' % int(network_id))
		self._wpa.request('ENABLE_NETWORK %d' % int(network_id))
		
		if not self._thread_connected_event.wait(timeout = timeout):
			raise Exception('Can\'t connect to ssid ' + str(ssid))
		self._thread_keep_connection = True
		self._thread_disconnected_event.clear()
		
		logger.debug('Connected to ssid %s' % ssid)
		
		return network_id
	
	def disconnect(self, network_id, raise_exceptions = True):
		"""
		Disconnect a Wi-Fi network
		If raise_exceptions (optional) is ${True}, this method raise an exception here if an unexpected disconnection happened since last call to Connect
		
		Example:
		| Disconnect | 'network_id' | ${True} |
		"""
		self._thread_keep_connection = False
		if raise_exceptions:
			self.check_connection(raise_exceptions)
		self._unexpected_disconnection = False
		
		self._thread_disconnected_event.clear()
		self._wpa.request('DISABLE_NETWORK %d' % int(network_id))
		
		if not self._thread_disconnected_event.wait(4):
			raise Exception('Can\'t disconnect from network ' + str(network_id))
		self._thread_connected_event.clear()
		
		logger.debug('Disconnected from network %d' % int(network_id))
	
	def check_connection(self, raise_exceptions = False):
		"""
		Check connection status
		Return ${False} if Wi-Fi connection has been unexpectedly lost since last Connect call (and raise an exception if Wi-Fi connection has been unexpectedly lost since last Connect call)
		Return ${True} otherwise
		
		Example:
		| Check Connection |
		=>
		| ${True} |
		"""
		if self._unexpected_disconnection and raise_exceptions:
			raise Exception('Connection lost')
		return not self._unexpected_disconnection

if __name__ == "__main__":
	import argparse
	import time
	
	parser = argparse.ArgumentParser(description="This program control wpa_supplicant daemon.", prog=progname)
	parser.add_argument('-s', '--socketdir', type=str, help='path to directory where wpa_sipplicant stores sockets')
	parser.add_argument('-i', '--ifname', type=str, help='wireless network interface to control', default='wlan0')
	
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
	wifiController.log_scanned_networks()
	print wifiController.scan()
	nid = wifiController.connect(ssid='mirabox', encryption='NONE')
	time.sleep(10)
	print wifiController.check_connection()
	time.sleep(10)
	wifiController.check_connection(True)
	wifiController.disconnect(nid)
	wifiController.stop()
else:
	from robot.api import logger

