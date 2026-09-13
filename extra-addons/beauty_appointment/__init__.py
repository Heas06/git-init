from . import controllers
from . import models


def _pre_init_salon(env):
    """Create the `btree_gist` extension before any table/constraint is built.

    The ``salon.appointment._no_overlap`` EXCLUDE constraint needs it. On module
    upgrades this hook does not run, so ``salon.appointment.init`` creates the
    extension too. A savepoint keeps a privilege error from poisoning the
    install transaction.
    """
    try:
        with env.cr.savepoint():
            env.cr.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    except Exception:  # noqa: BLE001 - insufficient privilege on some managed PG
        pass
