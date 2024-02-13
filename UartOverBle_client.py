"""
Add UART over BLE
UART over ble according to the NRF protocol
https://infocenter.nordicsemi.com/index.jsp?topic=%2Fcom.nordic.infocenter.sdk5.v14.0.0%2Fble_sdk_app_nus_eval.html
"""

import time
from datetime import datetime
import asyncio
import bleak
import inspect



####################### event loop #######################

class EventLoop_t:
	"a work-around for the Bleak DeprecationWarning: 'There is no current event loop' "
	_eventLoop = None

	@classmethod
	def __init__(self):
		if self._eventLoop is None: # the event loop need to be created only once during the entire run
			self._eventLoop = asyncio.new_event_loop()
			asyncio.set_event_loop(self._eventLoop)

	@classmethod
	def get_event_loop(self):
		return self._eventLoop
#end of class EventLoop_t

####################### events #######################
class asyncIoEvent_t:
	"a work-around for the issue of no standard way to deal with events in event-loop"
	__event = asyncio.Event()

	@classmethod
	def set(self):
		self.__event.set()

	@classmethod
	def clear(self):
		self.__event.clear()

	@classmethod
	async def wait(self, timeout: int = None) -> bool:
		if timeout is None:
			self.__event.wait()
		else:
			try:
				await asyncio.wait_for(self.__event.wait(), timeout)
			except asyncio.exceptions.CancelledError: #TODO: fix this. use a shield?
				return False
			except asyncio.exceptions.TimeoutError:
				return False
		return True
#end of class asyncIoEvent_t

####################### BLE CLASSES #######################
class BleScan_t:
	__bleDevice = None
	__BleDeviceName = None
	__deviceFoundEvent = asyncIoEvent_t()

	def __detectionCallback(self, device, advertisement_data):
		if device.name == self.__BleDeviceName:
			self.__bleDevice = device
			self.__deviceFoundEvent.set()


	async def __getBleDevice_run(self, BleDeviceName: str, bleScanTimeout: int):
		self.__BleDeviceName = BleDeviceName
		self.__bleDevice = None
		self.__deviceFoundEvent.clear()
		scanner = bleak.BleakScanner(detection_callback = self.__detectionCallback)
 
		await scanner.start()
		await self.__deviceFoundEvent.wait(bleScanTimeout)
		await scanner.stop()
		return self.__bleDevice


	async def __getClentList_run(self, bleScanTimeout: int):
		scanner = bleak.BleakScanner()
		await scanner.start()
		await asyncio.sleep(bleScanTimeout)
		await scanner.stop()
		return scanner.discovered_devices


	def getBleDevice(self, BleDeviceName: str, bleScanTimeout: int = 60) -> bleak.backends.device.BLEDevice:
		"""scan for and return a specific BLE device
		BleDeviceName: the name of the device to search for
		bleScanTimeout: maximum timeout in seconds"""
		loop = EventLoop_t().get_event_loop()
		return loop.run_until_complete(self.__getBleDevice_run(BleDeviceName, bleScanTimeout))


	def getClentList(self, bleScanTimeout: int = 60) -> list:
		"""BLE scan for BLE devices
		bleScanTimeout: scan time in seconds"""
		loop = EventLoop_t().get_event_loop()
		return loop.run_until_complete(self.__getClentList_run(bleScanTimeout))
#end of class BleScan_t


class BleClient_t:

	__recievedData: bytes = None
	__responseLength: int = 0
	__BleClient = None
	__txCharUUID = None
	__rxCharUUID = None
	__connectionTimeout = None
	__notifyEnabled = False
	__responseReceivedEvent = asyncIoEvent_t

	def __notificationCallback(self, sender: int, data: bytearray):
		if self.__recievedData == None:
			self.__recievedData = bytes()
		self.__recievedData += data
		if len(self.__recievedData) >= self.__responseLength:
			self.__responseReceivedEvent.set()


	async def __connect(self):
		startTime = int(time.time())
		while not self.__BleClient.is_connected:
			try:
				await self.__BleClient.connect()
			except Exception as e:
				print("failed to connect. retrying")

			if int(time.time()) - startTime > self.__connectionTimeout:
				print("failed to connect. aborting")
				break #timeout

		return self.__BleClient.is_connected


	async def __enalbeNotify(self, enable: bool):
		if enable == True and self.__notifyEnabled == False: # enable notifications if they are not enabled already
			await self.__BleClient.start_notify(self.__rxCharUUID, self.__notificationCallback)
			self.__notifyEnabled = True
		if enable == False and self.__notifyEnabled == True: # disable notifications if they are not disabled already
			await self.__BleClient.stop_notify(self.__rxCharUUID)
			self.__notifyEnabled = False


	async def __run(self, message: bytearray, responseTimeout: int, responseLength: int):
		self.__responseLength = responseLength
		self.__recievedData = None #clearing the value
		self.__responseReceivedEvent.clear()

		if responseLength > 0:
			if self.__rxCharUUID is None:
				raise ValueError("RX characteristic is None, can't receive messages")
			await self.__enalbeNotify(True)

		if message != None:
			if self.__txCharUUID is None:
				raise ValueError("TX characteristic is None, can't send messages")
			await self.__BleClient.write_gatt_char(self.__txCharUUID, message, False)

		if responseLength > 0:
			await self.__responseReceivedEvent.wait(responseTimeout)
			#await self.__enalbeNotify(False) #enableing this line will turn the notification off after every message

		return self.__recievedData


	def __getBleClient(self, BleDeviceName: str):
		BleScan = BleScan_t()
		bleDevice = BleScan.getBleDevice(BleDeviceName)
		if bleDevice == None:
			print("failed to get BLE device")
			return None
		BleClient = bleak.BleakClient(bleDevice.address)
		print(f"found BLE device {BleClient}")
		return BleClient


	async def __disconnect_run(self):
		if self.__BleClient != None and self.__BleClient.is_connected:
			await self.__enalbeNotify(False)
			try:
				await self.__BleClient.disconnect()
				self.__BleClient = None
				print("\nBLE disconnection")
			except:
				print("cought a timeout exception") #TODO: debug the timeout exception

	@classmethod
	def __init__(self, BleDeviceName: str, txCharUuid: str = "", rxCharUuid: str = "", connectionTimeout: int = 60):
		self.__BleClient = None
		self.__BleDeviceName = BleDeviceName
		self.__txCharUUID = txCharUuid
		self.__rxCharUUID = rxCharUuid
		self.__connectionTimeout = connectionTimeout


	def __del__(self):
		loop = EventLoop_t().get_event_loop()
		loop.run_until_complete(self.__disconnect_run())


	def __enter__(self):
		self.__BleClient = self.__getBleClient(self.__BleDeviceName)
		if self.__BleClient is None:
			return self
		loop = EventLoop_t().get_event_loop()
		isConnected = loop.run_until_complete(self.__connect())
		if isConnected is False:
			self.__BleClient = None
			return self
		# if await self.__BleClient.pair(2) is False:
		# 	await __disconnect_run()
		return self


	def __exit__(self, type, value, traceback):
		loop = EventLoop_t().get_event_loop()
		loop.run_until_complete(self.__disconnect_run())


	# public API


	def sendMessageAndWaitForNotification(self, message: bytearray = None, responseTimeout: int = 20, responseLength: int = 1) -> bytes:
		"""connect, send and recieve raw data to and from the BLE client
		message - optional message to send (can be None)
		responseTimeout - optional timeout for receiving response (0 for not waiting)
		responseLength - optional minimum number of bytes to wait for (0 for not receiving)"""
		if self.__BleClient == None:
			raise Exception("BleClient_t not initialized. make sure to use the \"with\" statement")
		loop = EventLoop_t().get_event_loop()
		return loop.run_until_complete(self.__run(message, responseTimeout, responseLength))
#end of class BleClient_t



####################### use exxamples #######################
def test_scan():
	print(f"{datetime.now()}: start {inspect.currentframe().f_code.co_name}")
	timeout = 3
	print(f"{datetime.now()}:{BleScan_t().getClentList(timeout)}")

def test_getDevice():
	print(f"{datetime.now()}: start {inspect.currentframe().f_code.co_name}")
	bleDevice = BleScan_t().getBleDevice("deviceName", 20)
	print(f"{datetime.now()}:{bleDevice}")

def test_connect():
	print(f"{datetime.now()}: start {inspect.currentframe().f_code.co_name}")
	BleDeviceName = "deviceName"
	RxcharUuid = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
	TxcharUuid = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

	with BleClient_t(BleDeviceName, TxcharUuid, RxcharUuid) as BleClient:
		message = bytes("010203", 'UTF-8')
		response = BleClient.sendMessageAndWaitForNotification(message=message, responseTimeout=30)
		print(f"{datetime.now()}: {response.hex()}")

