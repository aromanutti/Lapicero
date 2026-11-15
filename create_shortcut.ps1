# Creates "Lapicero" shortcuts on the Desktop and in the Start menu.
# They start the app with pythonw.exe (no console window) and can be opened with Ctrl+Alt+L.
# Run from this folder: powershell -ExecutionPolicy Bypass -File .\create_shortcut.ps1

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
$main = Join-Path $root "main.py"
$icon = Join-Path $root "lapicero\assets\lapicero.ico"

if (-not (Test-Path $pythonw)) {
    Write-Error "Missing $pythonw. Create the virtual environment first (see README)."
}

$shell = New-Object -ComObject WScript.Shell
$targets = @(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "Lapicero.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Programs")) "Lapicero.lnk")
)

foreach ($path in $targets) {
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $pythonw
    $link.Arguments = "`"$main`""
    $link.WorkingDirectory = $root
    $link.Description = "Lapicero handwritten notes"
    $link.IconLocation = "$icon,0"
    # Only one shortcut may own the hotkey; Windows ignores duplicates.
    if ($path -like "*Desktop*") { $link.Hotkey = "CTRL+ALT+L" }
    $link.Save()
    Write-Output "Created $path"
}
