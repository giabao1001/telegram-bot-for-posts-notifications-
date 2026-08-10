on run
    set appBundlePath to POSIX path of (path to me)
    set projectDirectory to do shell script "/usr/bin/dirname " & quoted form of appBundlePath
    set pythonPath to projectDirectory & "/.venv/bin/python"
    set managerPath to projectDirectory & "/pagepulse_launcher.py"
    set dashboardURL to "http://127.0.0.1:8000"
    set managerCommand to quoted form of pythonPath & " " & quoted form of managerPath

    try
        set currentStatus to do shell script managerCommand & " status"
    on error errorMessage
        display alert "diemRenLuyen could not check its status" message errorMessage as critical
        return
    end try

    if currentStatus starts with "managed|" or currentStatus starts with "autostart|" then
        set choice to button returned of (display dialog "diemRenLuyen is already running on this Mac." buttons {"Cancel", "Stop diemRenLuyen", "Open Dashboard"} default button "Open Dashboard" cancel button "Cancel" with title "diemRenLuyen")
        if choice is "Open Dashboard" then
            open location dashboardURL
        else if choice is "Stop diemRenLuyen" then
            try
                set resultMessage to do shell script managerCommand & " stop"
                display notification resultMessage with title "diemRenLuyen"
            on error errorMessage
                display alert "diemRenLuyen could not stop" message errorMessage as critical
            end try
        end if
        return
    end if

    if currentStatus starts with "external|" then
        set choice to button returned of (display dialog "PagePulse is already running outside this launcher. You can open it, but this launcher will not stop a process it did not start." buttons {"Cancel", "Open Dashboard"} default button "Open Dashboard" cancel button "Cancel" with title "PagePulse")
        if choice is "Open Dashboard" then open location dashboardURL
        return
    end if

    if currentStatus starts with "conflict|" then
        display alert "diemRenLuyen cannot start" message "Port 8000 is being used by another process. Stop that process, then open the launcher again." as critical
        return
    end if

    try
        set resultMessage to do shell script managerCommand & " start"
        display notification resultMessage with title "diemRenLuyen"
        open location dashboardURL
    on error errorMessage
        display alert "diemRenLuyen could not start" message errorMessage as critical
    end try
end run
