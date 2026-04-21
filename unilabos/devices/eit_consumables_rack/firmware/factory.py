
import time
import machine
import os
import network
import socket
from machine import Pin
import _thread
from machine import ADC
import bluetooth
import random
import struct
import micropython
from micropython import const
import struct


# Advertising payloads are repeated packets of the following form:
#   1 byte data length (N + 1)
#   1 byte type (see constants below)
#   N bytes type-specific data

_ADV_TYPE_FLAGS = const(0x01)
_ADV_TYPE_NAME = const(0x09)
_ADV_TYPE_UUID16_COMPLETE = const(0x3)
_ADV_TYPE_UUID32_COMPLETE = const(0x5)
_ADV_TYPE_UUID128_COMPLETE = const(0x7)
_ADV_TYPE_UUID16_MORE = const(0x2)
_ADV_TYPE_UUID32_MORE = const(0x4)
_ADV_TYPE_UUID128_MORE = const(0x6)
_ADV_TYPE_APPEARANCE = const(0x19)

_ADV_MAX_PAYLOAD = const(31)


# Generate a payload to be passed to gap_advertise(adv_data=...).
def advertising_payload(limited_disc=False, br_edr=False, name=None, services=None, appearance=0):
    payload = bytearray()

    def _append(adv_type, value):
        nonlocal payload
        payload += struct.pack("BB", len(value) + 1, adv_type) + value

    _append(
        _ADV_TYPE_FLAGS,
        struct.pack("B", (0x01 if limited_disc else 0x02) + (0x18 if br_edr else 0x04)),
    )

    if name:
        _append(_ADV_TYPE_NAME, name)

    if services:
        for uuid in services:
            b = bytes(uuid)
            if len(b) == 2:
                _append(_ADV_TYPE_UUID16_COMPLETE, b)
            elif len(b) == 4:
                _append(_ADV_TYPE_UUID32_COMPLETE, b)
            elif len(b) == 16:
                _append(_ADV_TYPE_UUID128_COMPLETE, b)

    # See org.bluetooth.characteristic.gap.appearance.xml
    if appearance:
        _append(_ADV_TYPE_APPEARANCE, struct.pack("<h", appearance))

    if len(payload) > _ADV_MAX_PAYLOAD:
        print(f'payload:{payload}')
        raise ValueError("advertising payload too large")

    return payload


def decode_field(payload, adv_type):
    i = 0
    result = []
    while i + 1 < len(payload):
        if payload[i + 1] == adv_type:
            result.append(payload[i + 2 : i + payload[i] + 1])
        i += 1 + payload[i]
    return result


def decode_name(payload):
    n = decode_field(payload, _ADV_TYPE_NAME)
    return str(n[0], "utf-8") if n else ""


def decode_services(payload):
    services = []
    for u in decode_field(payload, _ADV_TYPE_UUID16_COMPLETE):
        services.append(bluetooth.UUID(struct.unpack("<h", u)[0]))
    for u in decode_field(payload, _ADV_TYPE_UUID32_COMPLETE):
        services.append(bluetooth.UUID(struct.unpack("<d", u)[0]))
    for u in decode_field(payload, _ADV_TYPE_UUID128_COMPLETE):
        services.append(bluetooth.UUID(u))
    return services




_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)
_IRQ_GATTS_READ_REQUEST = const(4)
_IRQ_SCAN_RESULT = const(5)
_IRQ_SCAN_DONE = const(6)
_IRQ_PERIPHERAL_CONNECT = const(7)
_IRQ_PERIPHERAL_DISCONNECT = const(8)
_IRQ_GATTC_SERVICE_RESULT = const(9)
_IRQ_GATTC_SERVICE_DONE = const(10)
_IRQ_GATTC_CHARACTERISTIC_RESULT = const(11)
_IRQ_GATTC_CHARACTERISTIC_DONE = const(12)
_IRQ_GATTC_DESCRIPTOR_RESULT = const(13)
_IRQ_GATTC_DESCRIPTOR_DONE = const(14)
_IRQ_GATTC_READ_RESULT = const(15)
_IRQ_GATTC_READ_DONE = const(16)
_IRQ_GATTC_WRITE_DONE = const(17)
_IRQ_GATTC_NOTIFY = const(18)
_IRQ_GATTC_INDICATE = const(19)

_ADV_IND = const(0x00)
_ADV_DIRECT_IND = const(0x01)
_ADV_SCAN_IND = const(0x02)
_ADV_NONCONN_IND = const(0x03)

_UART_SERVICE_UUID = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
_UART_RX_CHAR_UUID = bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E")
_UART_TX_CHAR_UUID = bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E")


class BLESimpleCentral:
    def __init__(self, ble):
        self._ble = ble
        self._ble.active(True)
        self._ble.irq(self._irq)

        self._reset()

    def _reset(self):
        # Cached name and address from a successful scan.
        self._name = None
        self._addr_type = None
        self._addr = None

        # Callbacks for completion of various operations.
        # These reset back to None after being invoked.
        self._scan_callback = None
        self._conn_callback = None
        self._read_callback = None

        # Persistent callback for when new data is notified from the device.
        self._notify_callback = None

        # Connected device.
        self._conn_handle = None
        self._start_handle = None
        self._end_handle = None
        self._tx_handle = None
        self._rx_handle = None

    def _irq(self, event, data):
        if event == _IRQ_SCAN_RESULT:
            addr_type, addr, adv_type, rssi, adv_data = data
            if adv_type in (_ADV_IND, _ADV_DIRECT_IND) and _UART_SERVICE_UUID in decode_services(
                adv_data
            ):
                # Found a potential device, remember it and stop scanning.
                self._addr_type = addr_type
                self._addr = bytes(
                    addr
                )  # Note: addr buffer is owned by caller so need to copy it.
                self._name = decode_name(adv_data) or "?"
                self._ble.gap_scan(None)

        elif event == _IRQ_SCAN_DONE:
            if self._scan_callback:
                if self._addr:
                    # Found a device during the scan (and the scan was explicitly stopped).
                    self._scan_callback(self._addr_type, self._addr, self._name)
                    self._scan_callback = None
                else:
                    # Scan timed out.
                    self._scan_callback(None, None, None)

        elif event == _IRQ_PERIPHERAL_CONNECT:
            # Connect successful.
            conn_handle, addr_type, addr = data
            if addr_type == self._addr_type and addr == self._addr:
                self._conn_handle = conn_handle
                self._ble.gattc_discover_services(self._conn_handle)

        elif event == _IRQ_PERIPHERAL_DISCONNECT:
            # Disconnect (either initiated by us or the remote end).
            conn_handle, _, _ = data
            if conn_handle == self._conn_handle:
                # If it was initiated by us, it'll already be reset.
                self._reset()

        elif event == _IRQ_GATTC_SERVICE_RESULT:
            # Connected device returned a service.
            conn_handle, start_handle, end_handle, uuid = data
            print("service", data)
            if conn_handle == self._conn_handle and uuid == _UART_SERVICE_UUID:
                self._start_handle, self._end_handle = start_handle, end_handle

        elif event == _IRQ_GATTC_SERVICE_DONE:
            # Service query complete.
            if self._start_handle and self._end_handle:
                self._ble.gattc_discover_characteristics(
                    self._conn_handle, self._start_handle, self._end_handle
                )
            else:
                print("Failed to find uart service.")

        elif event == _IRQ_GATTC_CHARACTERISTIC_RESULT:
            # Connected device returned a characteristic.
            conn_handle, def_handle, value_handle, properties, uuid = data
            if conn_handle == self._conn_handle and uuid == _UART_RX_CHAR_UUID:
                self._rx_handle = value_handle
            if conn_handle == self._conn_handle and uuid == _UART_TX_CHAR_UUID:
                self._tx_handle = value_handle

        elif event == _IRQ_GATTC_CHARACTERISTIC_DONE:
            # Characteristic query complete.
            if self._tx_handle is not None and self._rx_handle is not None:
                # We've finished connecting and discovering device, fire the connect callback.
                if self._conn_callback:
                    self._conn_callback()
            else:
                print("Failed to find uart rx characteristic.")

        elif event == _IRQ_GATTC_WRITE_DONE:
            conn_handle, value_handle, status = data
            print("TX complete")

        elif event == _IRQ_GATTC_NOTIFY:
            conn_handle, value_handle, notify_data = data
            if conn_handle == self._conn_handle and value_handle == self._tx_handle:
                if self._notify_callback:
                    self._notify_callback(notify_data)

    # Returns true if we've successfully connected and discovered characteristics.
    def is_connected(self):
        return (
            self._conn_handle is not None
            and self._tx_handle is not None
            and self._rx_handle is not None
        )

    # Find a device advertising the environmental sensor service.
    def scan(self, callback=None,duration=2000):
        self._addr_type = None
        self._addr = None
        self._scan_callback = callback
        self._ble.gap_scan(duration, 30000, 30000)

    # Connect to the specified device (otherwise use cached address from a scan).
    def connect(self, addr_type=None, addr=None, callback=None):
        self._addr_type = addr_type or self._addr_type
        self._addr = addr or self._addr
        self._conn_callback = callback
        if self._addr_type is None or self._addr is None:
            return False
        self._ble.gap_connect(self._addr_type, self._addr)
        return True

    # Disconnect from current device.
    def disconnect(self):
        if self._conn_handle is None:
            return
        self._ble.gap_disconnect(self._conn_handle)
        self._reset()

    # Send data over the UART
    def write(self, v, response=False):
        if not self.is_connected():
            return
        self._ble.gattc_write(self._conn_handle, self._rx_handle, v, 1 if response else 0)

    # Set handler for when data is received over the UART.
    def on_notify(self, callback):
        self._notify_callback = callback


ble_state = False
def get_ble_state():
    global ble_state
    return ble_state

def ble_test():
    global ble_state,a
    # print('-----------ble_test--------------')
    ble = bluetooth.BLE()
    central = BLESimpleCentral(ble)
    a=0

    def on_scan(addr_type, addr, name):
        global a
        if addr_type is not None:
            # print("Found peripheral:", addr_type, addr, name)
            print("BT PASS\r")
            a = 1
            
        else:
            print('!!!! BT FAIL !!!!\r')
            a = 2


    central.scan(callback=on_scan)
    while a==0:
        time.sleep_ms(50)
    if a==1:
        ble_state=True
    elif a==2:
        ble_state=False
    central.scan(callback=on_scan,duration=None)












# RTU一共4个可控指示灯
led_4G = Pin(38, Pin.OUT)  # GPIO38 4G LED
led_wifi = Pin(39, Pin.OUT) # GPIO39 wifi LED
led_eth = Pin(40, Pin.OUT) # GPIO40 以太网 LED
led_sta = Pin(21, Pin.OUT) # GPIO21 运行 LED

led_state = 1
def sta_led_test():
    global led_state
    while True:
        if led_state==1:
            led_4G.value(1)
            time.sleep_ms(400)
            led_4G.value(0) 
            led_wifi.value(1)
            time.sleep_ms(400)
            led_wifi.value(0) 
            led_eth.value(1)
            time.sleep_ms(400)
            led_eth.value(0) 
            led_sta.value(1)
            time.sleep_ms(400)
            led_sta.value(0)
        elif led_state ==2:
            led_4G.value(1)
            led_wifi.value(1)
            led_eth.value(1)
            led_sta.value(1)

        

def led_disp_thread():
    _thread.start_new_thread(sta_led_test, ())

#DO1 --> pin21 --> GPIO15
#DO2 --> pin22 --> GPIO16
def relay_ctl(port,state):
    DO1 = Pin(15, Pin.OUT)
    DO2 = Pin(16, Pin.OUT)
    if port==1:
        DO1.value(state)
    elif port==2:
        DO2.value(state) 
    elif port==3:
        DO1.value(state)
        DO2.value(state) 


# ai测试案例
# ai1-gpio1,ai2-gpio11 电流测量范围0-20ma
ai1 = ADC(machine.Pin(1)) #ai1
ai1.atten(ADC.ATTN_0DB)  #使用0衰减，精度最高，输入电压范围：0-950mv
ai2 = ADC(machine.Pin(11)) #ai2
ai2.atten(ADC.ATTN_0DB)
vol = ADC(machine.Pin(10)) #电源
vol.atten(ADC.ATTN_0DB)


def get_ai_1_value():
    v1 = ai1.read_uv()
    #print('v1',v1)
    value1="%.4f" %(v1/1000000)
    #print("current value of ai1:",value1)    
    return float(value1)

def get_ai_2_value():
    v2 = ai2.read_uv()
    #print('v2',v2)
    value2="%.4f" %(v2/1000000)
    #print("current value of ai2:",value2)    
    return float(value2)

def get_ai_3_value():
    v3 = vol.read_uv()
    # print('v3',v3)
    value3="%.4f" %((v3/1000000)*40)
    # print("current value of ai3:",value3)    
    return float(value3)

    

'''
	     uart0	  uart1(232)  uart2(485)
--------------------------------------
tx gpio	  43        8        	18
--------------------------------------
rx gpio	  44        9		    17
'''

#TTL = machine.UART(0, baudrate=115200, tx=43, rx=44)    #machine.UART(串口号, 波特率, tx, rx) 
RS232 = machine.UART(1, baudrate=115200,tx=8, rx=9)
RS485 = machine.UART(2, baudrate=115200,tx=18, rx=17)
DI1 = machine.Pin(42, machine.Pin.IN)
DI2 = machine.Pin(41, machine.Pin.IN)


#测试标志物初始化
#------------------------------------
DI2_laba = False   
AI2_laba = False  
test_TF = True    
mqtt_connect_flag = False
test_SIM = False
state_485 = False
state_232 = False
test_tts = False
net_4g = False
upload = False
tf_state = False
di1_2 = False
di1_2_mun = 0
ai1_2 = False
wifi_state = False
ble_state = False
w5500 = False
#------------------------------------


def test_rs232():
    global state_232
    # print('-------------232_test------------')
    writeBuf1='12345'
    RS232.write(writeBuf1)
    time.sleep_ms(200)
    if RS232.any():
        readBuf1 = RS232.read().decode('utf-8')
        # print('write:',writeBuf1,type(writeBuf1))

        # print('rea:',readBuf1,type(readBuf1))
        if writeBuf1 == readBuf1:
            state_232 = True
            print('232 PASS\r')
        else:
            print('!!!! 232 FAIL !!!!\r')
    else:
        print('!!!! 232 FAIL !!!!\r')

#485测试
def test_rs485():
    global state_485
    data=''
    # print('-------------485_test------------')
    writeBuf1='12345'
    for i in range(2):
        #print(writeBuf1)
        RS485.write(writeBuf1)

        time.sleep_ms(200)
        if RS485.any():
            try:
                data = RS485.read().decode('utf-8')
            except:
                print('utf-8  test error')
    # print("Received data:", data)
    if writeBuf1 in data:
        state_485 = True
        print('485 PASS\r')
    else:
        print('!!!! 485 FAIL !!!!\r')


di1=False
di2=False
#继电器DI1,DI2测试
def test_app_relay():
    global di1,di2
    relay_ctl(3,0)
    diData11=DI1.value()
    print('DO1=0,DI1={}'.format(diData11))
    relay_ctl(1,1)
    time.sleep_ms(100)
    diData12=DI1.value()
    print('DO1=1,DI1={}'.format(diData12))
    if diData11 ==1 and diData12 ==0:
        di1=True
        print("DI1 DO1 PASS")
    else:
        print("DI1 DO1 FAIL")
    diData21=DI2.value()
    print('DO1=0,DI1={}'.format(diData21))
    relay_ctl(2,1)
    time.sleep_ms(100)
    diData22=DI2.value()
    print('DO1=1,DI1={}'.format(diData22))
    if diData21 ==1 and diData22 ==0:
        di2=True
        print("DI2 DO1 PASS")
    else:
        print("DI2 DO1 FAIL")


def test_ai1_2():
    global ai1,test_tts,AI2_laba,ai2,vin
    time.sleep_ms(100)
    if AI2_laba:        #喇叭功能
        aiData1=get_ai_1_value()    
        # print('aiData1:{}'.format(aiData1))
        if ((aiData1 > 9) and (aiData1 < 11)):
            print('AI1 PASS    {}\r'.format(aiData1))
            ai2 = True
        else:
            print('!!!! AI1 FAIL    {}  !!!!\r'.format(aiData1))
            ai2 = False
        
    else:       #测AI1/AI2功能
        aiData1=get_ai_1_value()
        aiData2=get_ai_2_value() 
        vol = get_ai_3_value()
        # print(aiData1+aiData2)
        if (aiData1 > 0.45) and (aiData1 < 0.55):
            print('AI1 PASS    {}'.format(aiData1))
            ai1 = True
        else:
            print('!!!! AI1 FAIL    {} !!!!'.format(aiData1))
            ai1 = False

        if (aiData2> 0.45) and (aiData2 < 0.55) :
            print('AI2 PASS    {}'.format(aiData2))
            ai2 = True
        else:
            print('!!!! AI2 FAIL    {} !!!!'.format(aiData2))
            ai2 = False

        if vol>10.8 and vol<13:
            print('VIN_ADC PASS    {}'.format(vol))
            vin = True
        else:
            print('!!!! VIN_ADC FAIL    {} !!!!'.format(vol))
            vin = False

def test_sd():
    global test_TF,tf_state
    if test_TF:
        # print('------------tf_test-------------')
        # 初始化SD卡
        try:
            sd = machine.SDCard(slot=0)
        except:
            print('have no T-CARD')
        time.sleep_ms(200)
        # 挂载SD卡
        try:
            os.mount(sd, "/sd")
            tf_state = True 
            print('T-CARD PASS\r')
        except OSError as e:
            print('!!!! T-CARD FAIL !!!!{}\r'.format(e))
        os.umount("/sd")
        # if tf_state:
        #     ret = os.listdir('/sd')
        #     print('SD card:{}\r'.format(ret))

def test_net_work():
    global net_4g
    # print('------------network_test-------------')
    lte = network.LTE()
    if not lte.isconnected():
        #print("Connecting to eth...")
        lte.active(True)
        ret = lte.connect(True)
        # print(ret,'--------------------------')
        if ret:
            print('4G PASS')
            net_4g = True
        else:
            print('!!!! 4G FAIL !!!!')

def test_w5500():
    global w5500
    # print('------------w5500_test-------------')
    # 定义全局变量
    eth = network.LAN()
    if not eth.isconnected():
        # print("Connecting to eth...")
        eth.ifconfig(('192.168.3.100', '255.255.255.0', '192.168.3.1', '192.168.3.1'))
        eth.active(True)
        # 循环等待直到连接成功
        a = 0
        while not eth.isconnected():
            pass
            a+=1
            time.sleep_ms(50)
            if a >=100:
                break
        if a>=100 :
            print('!!!! ETH FAIL !!!!\r',a)
        else:
            w5500 = True
            print("ETH PASS",a)



def test_wifi():
    # print('------------wifi_test-------------')
    global wifi_state
    wlan = network.WLAN(network.STA_IF)
    # 激活Wi-Fi接口
    wlan.active(True)
    # 执行Wi-Fi扫描
    scan_result = wlan.scan()

    # 打印扫描到的所有Wi-Fi网络及其信息
    for ap in scan_result:
        SSID = ap[0].decode()
        RSSI = ap[3]
        if ap[0].decode()!=None:
            wifi_state = True
            print("WiFi PASS")
            break
        else:
            print('!!!! WiFi FAIL !!!!\r')
            break
        
    wlan.active(False)


    

def main():
    global test_SIM,state_485,state_232,net_4g,tf_state,di1,di2,AI2_laba,test_TF,ble_state,wifi_state,led_state,w5500,ai1,ai2,vin
    led_disp_thread()   #LED灯
    print('** ------------------------------------------------------------------------------- **\r')
    test_rs232()    #232测试
    test_rs485()    #485测试1
    test_sd()    #tft卡测试
    ble_test()   #蓝牙测试
    time.sleep_ms(200)
    ble_state =get_ble_state()
    test_app_relay()    #继电器DI1,DI2测试
    test_ai1_2()    #电流AI1,AI2测试
    test_w5500()
    test_wifi()     #wifi测试
    test_net_work()    #检测网络连接
    print('*****************************************************\r')
    if net_4g and state_485 and state_232 and tf_state and di1 and di2 and ai1 and ai2 and vin and ble_state and wifi_state and w5500:
        pass
        print('ALL TEST PASS')
    else:
        led_state = 2
        if net_4g :
            pass
        else:
            print("4G FAIL")
        if state_485 :
            pass
        else:
            print("485 FAIL")
        if state_232 :
            pass
        else:
            print("232 FAIL")
        if tf_state :
            pass
        else:
            print('T-CARD FAIL')
        if di1:
            pass
        else:
            print('DI1 DO1 FAIL')
        if di2:
            pass
        else:
            print('DI2 DO2 FAIL')
        if ai1 :
            pass
        else:
            print('AI1 FAIL')
        if ai2 :
            pass
        else:
            print('AI2 FAIL')
        if vin :
            pass
        else:
            print('VIN_ADC FAIL')
        if ble_state :
            pass
        else:
            print('BT FAIL')
        if wifi_state :
            pass
        else:
            print('WiFi FAIL')
        if w5500 :
            pass
        else:
            print('ETH FAIL')
    print('*****************************************************\r')
    while 1:
        time.sleep(1)






main()




