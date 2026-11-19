"""Frozen, visible Windows service. Normal administrator stop/uninstall is supported."""
import sys
import threading
import traceback
import servicemanager
import win32service
import win32serviceutil
from focuslock.service_core import SessionService, SERVICE_NAME
from focuslock.service_ipc import serve


class StayLockedService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = 'StayLocked Focus Service'
    _svc_description_ = 'User-requested focus sessions. End on timer expiry or Windows restart. Manual start only.'

    def __init__(self, args):
        super().__init__(args)
        self.core = SessionService()

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING, waitHint=60000)
        self.core.stop()

    def SvcShutdown(self):
        self.SvcStop()

    def SvcDoRun(self):
        threads = [threading.Thread(target=serve, args=(self.core, control), daemon=True)
                   for control in (False, True)]
        try:
            for thread in threads:
                thread.start()
            while not self.core.stop_event.wait(.25):
                if any(not thread.is_alive() for thread in threads):
                    raise RuntimeError('Service pipe listener exited unexpectedly.')
        except Exception:
            servicemanager.LogErrorMsg(traceback.format_exc())
        finally:
            self.core.stop()
            self.core.join()
            for thread in threads:
                thread.join(5)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        from focuslock.service_admin import main
        raise SystemExit(main(sys.argv[1:]))
    # SCM launches without an interactive console; legacy network diagnostics must not
    # fail because stdout has no valid Windows handle. Errors use Event Viewer.
    import os
    sys.stdout = sys.stderr = open(os.devnull, 'w', encoding='utf-8')
    servicemanager.Initialize()
    servicemanager.PrepareToHostSingle(StayLockedService)
    servicemanager.StartServiceCtrlDispatcher()
