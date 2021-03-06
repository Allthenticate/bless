import sys
import uuid
import pytest
import aioconsole

import numpy as np

if sys.platform.lower() != "win32":
    pytest.skip("Only for windows", allow_module_level=True)

from typing import List  # noqa: E402

hardware_only = pytest.mark.skipif("os.environ.get('TEST_HARDWARE') is None")

from bleak.backends.dotnet.utils import (  # noqa: E402
        wrap_IAsyncOperation,
        BleakDataWriter
        )

from bless.backends.characteristic import (  # noqa: E402
        GattCharacteristicsFlags,
        GATTAttributePermissions
        )
from bless.backends.dotnet.utils import sync_async_wrap  # noqa: E402

from Windows.Foundation import (  # noqa: E402
        IAsyncOperation,
        Deferral
        )

from Windows.Storage.Streams import DataReader, DataWriter  # noqa: E402

from Windows.Devices.Bluetooth.GenericAttributeProfile import (  # noqa: E402 F401 E501
    GattWriteOption,
    GattServiceProviderResult,
    GattServiceProvider,
    GattLocalService,
    GattLocalCharacteristicResult,
    GattLocalCharacteristic,
    GattLocalCharacteristicParameters,
    GattServiceProviderAdvertisingParameters,
    GattReadRequestedEventArgs,
    GattReadRequest,
    GattWriteRequestedEventArgs,
    GattWriteRequest,
    GattSubscribedClient
)

from System import (  # noqa: E402
    Guid,
    Object
)


@hardware_only
class TestServiceProvider:
    """
    Test
    """
    hex_words: List[str] = [
            'DEAD', 'FACE', 'BABE',
            'CAFE', 'FADE', 'BAD',
            'DAD', 'ACE', 'BED'
            ]

    val: bytearray = bytearray([0])

    _subscribed_clients: List = []

    @pytest.mark.asyncio
    async def test_init(self):

        def read(
                sender: GattLocalCharacteristic,
                args: GattReadRequestedEventArgs
                ):
            deferral: Deferral = args.GetDeferral()
            value = self.val
            writer: DataWriter = DataWriter()
            writer.WriteBytes(value)
            request: GattReadRequest = sync_async_wrap(
                GattReadRequest,
                args.GetRequestAsync
            )
            request.RespondWithValue(writer.DetachBuffer())
            deferral.Complete()

        def write(
                sender: GattLocalCharacteristic,
                args: GattWriteRequestedEventArgs
                ):
            deferral: Deferral = args.GetDeferral()
            request: GattWriteRequest = sync_async_wrap(
                    GattWriteRequest,
                    args.GetRequestAsync
                    )
            reader: DataReader = DataReader.FromBuffer(request.Value)
            n_bytes: int = reader.UnconsumedBufferLength
            value: bytearray = bytearray()
            for n in range(0, n_bytes):
                next_byte: int = reader.ReadByte()
                value.append(next_byte)
            self.val = value

            if request.Option == GattWriteOption.WriteWithResponse:
                request.Respond()

            deferral.Complete()

        def subscribe(
                sender: GattLocalCharacteristic,
                args: Object
                ):
            self._subscribed_clients = list(sender.SubscribedClients)

        # Create service
        service_uuid: str = str(uuid.uuid4())
        service_guid: Guid = Guid.Parse(service_uuid)
        ServiceProviderResult: GattServiceProviderResult = (
                await wrap_IAsyncOperation(
                    IAsyncOperation[GattServiceProviderResult](
                        GattServiceProvider.CreateAsync(service_guid)),
                    return_type=GattServiceProviderResult)

                )
        service_provider: GattServiceProvider = (
                ServiceProviderResult.ServiceProvider
                )

        new_service: GattLocalService = service_provider.Service

        # Add a characteristic
        char_uuid: str = str(uuid.uuid4())
        char_guid: Guid = Guid.Parse(char_uuid)

        properties: GattCharacteristicsFlags = (
                GattCharacteristicsFlags.read |
                GattCharacteristicsFlags.write |
                GattCharacteristicsFlags.notify
                )

        permissions: GATTAttributePermissions = (
                GATTAttributePermissions.readable |
                GATTAttributePermissions.writeable
                )

        ReadParameters: GattLocalCharacteristicParameters = (
                GattLocalCharacteristicParameters()
                )
        ReadParameters.CharacteristicProperties = properties.value
        ReadParameters.ReadProtectionLevel = permissions.value

        characteristic_result: GattLocalCharacteristicResult = (
                await wrap_IAsyncOperation(
                    IAsyncOperation[GattLocalCharacteristicResult](
                        new_service.CreateCharacteristicAsync(
                            char_guid,
                            ReadParameters
                            )
                        ),
                    return_type=GattLocalCharacteristicResult)
                )
        newChar: GattLocalCharacteristic = characteristic_result.Characteristic
        newChar.ReadRequested += read
        newChar.WriteRequested += write
        newChar.SubscribedClientsChanged += subscribe

        # Ensure we're not advertising
        assert service_provider.AdvertisementStatus != 2

        # Advertise
        adv_parameters: GattServiceProviderAdvertisingParameters = (
                GattServiceProviderAdvertisingParameters()
                )
        adv_parameters.IsDiscoverable = True
        adv_parameters.IsConnectable = True

        service_provider.StartAdvertising(adv_parameters)

        # Check
        assert service_provider.AdvertisementStatus == 2

        # We shouldn't be connected
        assert len(self._subscribed_clients) < 1

        print(
                "\nPlease connect now" +
                "and subscribe to the characteristic {}..."
                .format(char_uuid)
                )
        await aioconsole.ainput("Press enter when ready...")

        assert len(self._subscribed_clients) > 0

        # Read test
        rng: np.random._generator.Generator = np.random.default_rng()
        hex_val: str = ''.join(rng.choice(self.hex_words, 2, replace=False))
        self.val = bytearray(
                int(f"0x{hex_val}", 16).to_bytes(
                    length=int(np.ceil(len(hex_val)/2)),
                    byteorder='big'
                    )
                )

        print("Trigger a read and enter the hex value you see below")
        entered_value = await aioconsole.ainput("Value: ")
        assert entered_value == hex_val

        # Write test
        hex_val = ''.join(rng.choice(self.hex_words, 2, replace=False))
        print(f"Set the characteristic to the following: {hex_val}")
        await aioconsole.ainput("Press enter when ready...")
        str_val: str = ''.join([hex(x)[2:] for x in self.val]).upper()
        assert str_val == hex_val

        # Notify test
        hex_val = ''.join(rng.choice(self.hex_words, 2, replace=False))
        self.val = bytearray(
                int(f"0x{hex_val}", 16).to_bytes(
                    length=int(np.ceil(len(hex_val)/2)),
                    byteorder='big'
                    )
                )

        print("A new value will be sent")
        await aioconsole.ainput("Press enter to receive the new value...")

        with BleakDataWriter(self.val) as writer:
            newChar.NotifyValueAsync(
                    writer.detach_buffer()
                    )

        new_value: str = await aioconsole.ainput("Enter the New value: ")
        assert new_value == hex_val

        # unsubscribe
        print("Unsubscribe from the characteristic")
        await aioconsole.ainput("Press enter when ready...")
        assert len(self._subscribed_clients) < 1

        # Stop Advertising
        service_provider.StopAdvertising()
        assert service_provider.AdvertisementStatus != 2
