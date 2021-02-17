import asyncio
import logging
from asyncio import AbstractEventLoop
from typing import Optional, Dict, List, Any

from bless.backends.bluezdbus.application import BlueZGattApplication
from bless.backends.bluezdbus.characteristic import BlueZGattCharacteristic, Flags
from bless.backends.bluezdbus.service import BlueZGattService
from bless.backends.bluezdbus.utils import get_adapter
from bless.backends.characteristic import GattCharacteristicsFlags
from bless.backends.server import BaseBlessServer
from twisted.internet.asyncioreactor import AsyncioSelectorReactor
from txdbus import client
from txdbus.objects import RemoteDBusObject

import bleak.backends.bluezdbus.defs as defs
from bleak.backends.bluezdbus.characteristic import BleakGATTCharacteristicBlueZDBus
from bleak.backends.bluezdbus.service import BleakGATTServiceBlueZDBus

logger = logging.getLogger(__name__)
import uuid


class BlessServerBlueZDBus(BaseBlessServer):
    """
    The BlueZ DBus implementation of the Bless Server

    Attributes
    ----------
    name : str
        The name of the server that will be advertised]

    """

    def __init__(self, name: str, loop: AbstractEventLoop = None, **kwargs):
        super(BlessServerBlueZDBus, self).__init__(loop=loop, **kwargs)
        self.name: str = name
        self.reactor: AsyncioSelectorReactor = AsyncioSelectorReactor(loop)

        self.services: Dict[str, BleakGATTServiceBlueZDBus] = {}

        # Keep track of the hardware path to the adapter
        if kwargs.get("path"):
            self.adapter_path = f"/org/bluez/{kwargs.get('path')}/"
            logger.debug(f"Adapter path specified: {self.adapter_path}")
        else:
            self.adapter_path = "/org/bluez/hci0/"
            logger.debug(
                f"No adapter path specified, defaulting to: {self.adapter_path}"
            )

        self.setup_task: asyncio.Task = self.loop.create_task(self.setup())

        # Callback functions
        self.connected_callback = lambda _: None
        self.disconnected_callback = lambda _: None

    async def setup(self):
        """
        Asyncronous side of init
        """
        self.bus: client = await client.connect(self.reactor, "system").asFuture(
            self.loop
        )

        gatt_name: str = self.name.replace(" ", "")
        self.app: BlueZGattApplication = BlueZGattApplication(
            gatt_name, "org.bluez." + gatt_name, self.bus, self.loop
        )

        self.app.Read = self.read
        self.app.Write = self.write

        # We don't need to define these
        self.app.StartNotify = lambda x: None
        self.app.StopNotify = lambda x: None

        self.adapter: RemoteDBusObject = await get_adapter(self.bus, self.loop)

    async def start(self, **kwargs) -> bool:
        """
        Start the server

        Returns
        -------
        bool
            Whether the server started successfully
        """
        await self.setup_task

        # Make our app available
        self.bus.exportObject(self.app)
        await self.bus.requestBusName(self.app.destination).asFuture(self.loop)

        # Register
        await self.app.register(self.adapter)

        # advertise
        await self.app.start_advertising(self.adapter)

        return True

    async def stop(self) -> bool:
        """
        Stop the server

        Returns
        -------
        bool
            Whether the server stopped successfully
        """
        # Stop Advertising
        await self.app.stop_advertising(self.adapter)

        # Unregister
        await self.app.unregister(self.adapter)

        return True

    async def is_connected(self) -> bool:
        """
        Determine whether there are any connected peripheral devices

        Returns
        -------
        bool
            Whether any peripheral devices are connected
        """
        return await self.app.is_connected()

    async def is_advertising(self) -> bool:
        """
        Determine whether the server is advertising

        Returns
        -------
        bool
            True if the server is advertising
        """
        await self.setup_task
        return await self.app.is_advertising(self.adapter)

    async def add_new_service(self, service_uuid: [str, uuid.UUID]):
        """
        Add a new GATT service to be hosted by the server

        Parameters
        ----------
        service_uuid : str, uuid.UUID
            The UUID for the service to add
        """
        await self.setup_task

        # Convert the type in case it is uuid.UUID
        service_uuid = str(service_uuid).lower()

        gatt_service: BlueZGattService = await self.app.add_service(service_uuid)
        dbus_obj: RemoteDBusObject = await self.bus.getRemoteObject(
            self.app.destination, gatt_service.path
        ).asFuture(self.loop)
        dict_obj: Dict = await dbus_obj.callRemote(
            "GetAll", defs.GATT_SERVICE_INTERFACE, interface=defs.PROPERTIES_INTERFACE
        ).asFuture(self.loop)
        service: BleakGATTServiceBlueZDBus = BleakGATTServiceBlueZDBus(
            dict_obj, gatt_service.path
        )
        self.services[service_uuid] = service

    async def add_new_characteristic(
        self,
        service_uuid: [str, uuid.UUID],
        char_uuid: [str, uuid.UUID],
        properties: GattCharacteristicsFlags,
        value: Optional[bytearray],
        permissions: int,
    ):
        """
        Add a new characteristic to be associated with the server

        Parameters
        ----------
        service_uuid : str, uuid.UUID
            The string representation of the UUID of the GATT service to which
            this new characteristic should belong
        char_uuid : str, uuid.UUID
            The string representation of the UUID of the characteristic
        properties : GattCharacteristicsFlags
            GATT Characteristic Flags that define the characteristic
        value : Optional[bytearray]
            A byterray representation of the value to be associated with the
            characteristic. Can be None if the characteristic is writable
        permissions : int
            GATT Characteristic flags that define the permissions for the
            characteristic
        """
        await self.setup_task
        flags: List[Flags] = Flags.from_bless(properties)
        logger.debug(
            f"Adding new characteristic {char_uuid} to service: {service_uuid} with flags: {flags}"
        )

        # Standardize the service and char uuids
        service_uuid = str(service_uuid).lower()
        char_uuid = str(char_uuid).lower()

        # DBus can't handle None values
        if value is None:
            value = bytearray(b"")

        # Add to our BlueZDBus app
        gatt_char: BlueZGattCharacteristic = await self.app.add_characteristic(
            service_uuid, char_uuid, value, flags
        )
        dbus_obj: RemoteDBusObject = await self.bus.getRemoteObject(
            self.app.destination, gatt_char.path
        ).asFuture(self.loop)
        dict_obj: Dict = await dbus_obj.callRemote(
            "GetAll",
            defs.GATT_CHARACTERISTIC_INTERFACE,
            interface=defs.PROPERTIES_INTERFACE,
        ).asFuture(self.loop)

        # Create a Bleak Characteristic
        char: BleakGATTCharacteristicBlueZDBus = BleakGATTCharacteristicBlueZDBus(
            dict_obj, gatt_char.path, service_uuid
        )

        # Add it to the service
        self.services[service_uuid].add_characteristic(char)

    def update_value(self, service_uuid: str, char_uuid: str) -> bool:
        """
        Update the characteristic value. This is different than using
        characteristic.set_value. This method ensures that subscribed devices
        receive notifications, assuming the characteristic in question is
        notifyable

        Parameters
        ----------
        service_uuid : str
            The string representation of the UUID for the service associated
            with the characteristic whose value is to be updated
        char_uuid : str
            The string representation of the UUID for the characteristic whose
            value is to be updated

        Returns
        -------
        bool
            Whether the characteristic value was successfully updated
        """
        bless_service: BleakGATTServiceBlueZDBus = self.services[service_uuid]
        bless_char: BleakGATTCharacteristicBlueZDBus = bless_service.get_characteristic(
            char_uuid
        )

        if not bless_char:
            logger.debug("Characteristic not found, unable to update")
            return False

        logger.debug("Characteristic found, updating...")

        try:
            cur_value: Any = bless_char.value
        except:
            logger.debug("No set value for characteristic, unable to update")
            return False

        service: BlueZGattService = next(
            iter(
                [
                    service
                    for service in self.app.services
                    if service.uuid == service_uuid
                ]
            )
        )

        characteristic: BlueZGattCharacteristic = service.get_characteristic(
            char_uuid=char_uuid
        )
        characteristic.value = cur_value

    def read(self, char: BlueZGattCharacteristic) -> bytearray:
        """
        Read request.
        This re-routes the the request incomming on the dbus to the server to
        be re-routed to the user defined handler

        Parameters
        ----------
        char : BlueZGattCharacteristic
            The characteristic passed from the app

        Returns
        -------
        bytearray
            The value of the characteristic
        """
        return self.read_request(char.uuid)

    def write(self, char: BlueZGattCharacteristic, value: bytearray):
        """
        Write request.
        This function re-routes the write request sent from the
        BlueZGattApplication to the server function for re-route to the user
        defined handler

        Parameters
        ----------
        char : BlueZGattCharacteristic
            The characteristic object involved in the request
        value : bytearray
            The value being requested to set
        """
        return self.write_request(char.uuid, value)

    async def disconnect(self, device_mac: str) -> bool:
        """
        Disconnect from a connected central via the mac address of the device by sending a commmand
        over the session bus to disconnect.
        :param device_mac: mac address of the device to disconnect from
        :type device_mac: str
        :return: `True`, If successful disconnect, `False` otherwise
        :rtype: bool
        """
        # Convert the mac to the device path on the session bus
        device_path = f"{self.adapter_path}dev_{device_mac.replace(':', '_')}"

        logger.debug(f"Attempting to disconnect from: {device_path}")
        try:
            await self.bus.callRemote(
                device_path,
                "Disconnect",
                interface=defs.DEVICE_INTERFACE,
                destination=defs.BLUEZ_SERVICE,
            ).asFuture(self.loop)
        except Exception:
            logger.exception(f"Attempt to disconnect central {device_mac} failed!")
            return False
        logger.info(f"Disconnected from {device_path} successfully!")
        return True

    async def set_connected_callback(self, callback_function) -> bool:
        """
        Assigns a callback function to the InterfacesAdded member of the DBus Object manager, note that the
        callback function will be passed a `txdbus.message.SignalMessage` object.
        :param callback_function:
        :type callback_function: function
        :return: `True` if callback function added successfully, `False`, otherwise
        :rtype: bool
        """
        if not callable(callback_function):
            logger.info("Callback function is not valid! Must be a function!")
            return False

        logger.info(f"Setting up connected callback function: {callback_function}")
        self.connected_callback = callback_function
        try:
            await self.bus.addMatch(
                self.connected_callback,
                interface="org.freedesktop.DBus.ObjectManager",
                member="InterfacesAdded",
            ).asFuture(self.loop)
        except Exception:
            logger.exception("Unable to setup connected callback")
            return False
        logger.info("Connected callback setup successfully!")
        return True

    async def set_disconnected_callback(self, callback_function) -> bool:
        """
        Assigns a callback function to the InterfacesRemoved member of the DBus Object manager, note that the
        callback function will be passed a `txdbus.message.SignalMessage` object.
        :param callback_function:
        :type callback_function: function
        :return: `True` if callback function added successfully, `False`, otherwise
        :rtype: bool
        """
        if not callable(callback_function):
            logger.info("Callback function is not valid! Must be a function!")
            return False

        logger.info(f"Setting up disconnect callback function: {callback_function}")
        self.disconnected_callback = callback_function
        try:
            await self.bus.addMatch(
                self.disconnected_callback,
                interface="org.freedesktop.DBus.ObjectManager",
                member="InterfacesRemoved",
            ).asFuture(self.loop)
        except Exception:
            logger.exception("Unable to setup disconnect callback")
            return False
        logger.info("Disconnect callback setup successfully!")
        return True

    # TODO(Bernie): This was a possible callback route, keeping for future reference
    # def _parse_properties_changed(self, message):
    #     """
    #     This is a work in progress for parsing properties changed
    #     :param message:
    #     :type message:
    #     :return:
    #     :rtype:
    #     """
    #     if message.member == "PropertiesChanged":
    #         # logger.debug('Got properties changed message!')
    #         interface, changed, invalidated = message.body
    #
    #         # Make sure that it was on the right interface
    #         if interface != defs.DEVICE_INTERFACE:
    #             return
    #
    #         # The changed dict contains what changed
    #         if "Connected" in changed.keys():
    #             if not changed.get("Connected"):
    #                 logger.debug("A device disconnected!")
    #
    #                 # self.disconnected_callback(message)
    #                 return
    #
    #         else:
    #             # logger.debug("Reached properties changed message we aren't interested in, returning")
    #             return
    #     else:
    #         logger.info(f"Unexpected message off the dbus: {message.member}")
    #
    # async def setup_properties_changed(self):
    #     await self.bus.addMatch(
    #             self._parse_properties_changed,
    #             interface="org.freedesktop.DBus.Properties",
    #             member="PropertiesChanged",
    #     ).asFuture(self.loop)
