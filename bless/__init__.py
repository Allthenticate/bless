# type: ignore
import sys

if sys.platform == 'darwin':

    # Server
    from bless.backends.corebluetooth.server import (  # noqa: F401
            BlessServerCoreBluetooth as BlessServer
            )

    # Characteristic Classes
    from bless.backends.corebluetooth.characteristic import (  # noqa: F401
            BlessGATTCharacteristicCoreBluetooth
            as BlessGATTCharacteristic
            )

elif sys.platform == 'win32':

    # Server
    from bless.backends.dotnet.server import (
            BlessServerDotNet as BlessServer
    )

    # Characteristic Classes
    from bless.backends.dotnet.characteristic import (
            BlessGATTCharacteristicDotNet
            as BlessGATTCharacteristic
    )

# type: ignore
from bless.backends.characteristic import (  # noqa: E402 F401
        GattCharacteristicsFlags,
        GATTAttributePermissions
        )


def check_test() -> bool:
    """
    Verify that testing is functional

    Returns
    -------
    bool
        Default to true
    """
    return True