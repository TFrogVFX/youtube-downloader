# YouTube Downloader (by tfrog) - installer, started by YouTube-Downloader.exe (or install.bat)
# Installs: Python 3.12 (if missing), FFmpeg, Deno and an own Python environment with yt-dlp + PySide6,
# and creates shortcuts on the desktop and in the Start menu. Run again to update the app.

param([switch]$Exe)   # -Exe: started by YouTube-Downloader.exe (keep window open on errors)

$ErrorActionPreference = 'Continue'
$AppName = 'YouTube Downloader'
$AppVersion = '2.9.5'
$OldNames = @('tfrog YT Clip')
$AppDir  = Join-Path $env:LOCALAPPDATA 'tfrog_ytclip'
$Script  = 'tfrog_ytclip.pyw'

function Step($t) { Write-Host ''; Write-Host "== $t" -ForegroundColor Green }
function Info($t) { Write-Host "   $t" -ForegroundColor DarkGray }
function Warn($t) { Write-Host "   $t" -ForegroundColor Yellow }
function Fail($t) {
    Write-Host ''; Write-Host "ERROR: $t" -ForegroundColor Red
    if ($Exe) { Read-Host 'Press Enter to close' | Out-Null }
    exit 1
}
function Has($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Write-Launcher([string]$pyw, [string]$script) {
    # read by the .exe launcher (UTF-16LE, no BOM): line 1 = pythonw.exe, line 2 = script
    $enc = New-Object System.Text.UnicodeEncoding($false, $false)
    [IO.File]::WriteAllText((Join-Path $AppDir 'launcher.txt'), "$pyw`r`n$script`r`n", $enc)
}

function Register-Uninstall([string]$key, [string]$name, [string]$icon) {
    # entry in Windows Settings > Apps, so the app can be removed without the ZIP
    try {
        $uk = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$key"
        New-Item -Path $uk -Force | Out-Null
        $ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $vals = @{
            DisplayName = $name; DisplayVersion = $AppVersion; Publisher = 'tfrog'
            InstallLocation = $AppDir; DisplayIcon = $icon
            UninstallString = "`"$ps`" -NoProfile -ExecutionPolicy Bypass -File `"$AppDir\uninstall.ps1`""
        }
        foreach ($k in $vals.Keys) { New-ItemProperty -Path $uk -Name $k -Value $vals[$k] -PropertyType String -Force | Out-Null }
        foreach ($k in @('NoModify', 'NoRepair')) { New-ItemProperty -Path $uk -Name $k -Value 1 -PropertyType DWord -Force | Out-Null }
        $kb = [int]((Get-ChildItem $AppDir -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum / 1KB)
        New-ItemProperty -Path $uk -Name 'EstimatedSize' -Value $kb -PropertyType DWord -Force | Out-Null
        Info 'Added to Windows Settings > Apps (for uninstalling)'
    } catch {
        Warn "Could not register the uninstaller ($($_.Exception.Message))"
    }
}

function Test-AppRunning([string]$script) {
    $p = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*$script*" }
    return [bool]$p
}

function Set-ShortcutAppId([string]$lnkPath, [string]$appId) {
    # Writes System.AppUserModel.ID into the .lnk so Windows keeps the app on its own taskbar entry
    try {
        if (-not ('TfrogLnk' -as [type])) {
            Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

public static class TfrogLnk {
    [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
    class CShellLink { }

    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
    interface IPropertyStore {
        void GetCount(out uint cProps);
        void GetAt(uint iProp, out PropKey pkey);
        void GetValue(ref PropKey key, IntPtr pv);
        void SetValue(ref PropKey key, ref PropVar pv);
        void Commit();
    }

    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    struct PropKey { public Guid fmtid; public uint pid; }

    [StructLayout(LayoutKind.Explicit, Size = 24)]
    struct PropVar { [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr ptr; }

    public static void SetAppId(string path, string appId) {
        object link = new CShellLink();
        try {
            IPersistFile file = (IPersistFile)link;
            file.Load(path, 2);
            IPropertyStore store = (IPropertyStore)link;
            PropKey key = new PropKey();
            key.fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3");
            key.pid = 5;
            PropVar pv = new PropVar();
            pv.vt = 31;
            pv.ptr = Marshal.StringToCoTaskMemUni(appId);
            try { store.SetValue(ref key, ref pv); store.Commit(); }
            finally { Marshal.FreeCoTaskMem(pv.ptr); }
            file.Save(path, true);
        } finally {
            Marshal.ReleaseComObject(link);
        }
    }
}
'@
        }
        [TfrogLnk]::SetAppId($lnkPath, $appId)
    } catch {
        Warn "Taskbar ID not set for $lnkPath ($($_.Exception.Message))"
    }
}

function Refresh-Path {
    $parts = @(
        [Environment]::GetEnvironmentVariable('Path', 'Machine'),
        [Environment]::GetEnvironmentVariable('Path', 'User'),
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links",
        "$env:ProgramFiles\WinGet\Links",
        "$env:USERPROFILE\.deno\bin"
    )
    $env:Path = ($parts | Where-Object { $_ }) -join ';'
}

function Winget-Install($id) {
    Info "winget install $id"
    winget install -e --id $id --silent --accept-source-agreements --accept-package-agreements
    Refresh-Path
}

function Test-Py([string]$exe, [string[]]$pre) {
    try {
        $out = & $exe @pre -c "import sys; print(sys.executable if sys.version_info[:2] == (3, 12) else '')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) {
            $p = ($out | Select-Object -Last 1).Trim()
            if ($p -and (Test-Path $p)) { return $p }
        }
    } catch {}
    return $null
}

function Find-Python312 {
    if (Has 'py')     { $p = Test-Py 'py' @('-3.12'); if ($p) { return $p } }
    if (Has 'python') { $p = Test-Py 'python' @();    if ($p) { return $p } }
    foreach ($c in @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
                     "$env:ProgramFiles\Python312\python.exe")) {
        if (Test-Path $c) { $p = Test-Py $c @(); if ($p) { return $p } }
    }
    return $null
}

Write-Host "$AppName (by tfrog) - Setup" -ForegroundColor Cyan
if (-not (Test-Path (Join-Path $PSScriptRoot $Script))) { Fail "$Script not found. Please extract the whole ZIP first." }
if (-not (Has 'winget')) { Fail 'winget is missing. Install "App Installer" from the Microsoft Store and run this again.' }
Refresh-Path
if (Test-AppRunning $Script) { Fail 'The YouTube Downloader is still running - please close it and start the setup again.' }

Step '1/5  Python 3.12'
$py = Find-Python312
if (-not $py) { Winget-Install 'Python.Python.3.12'; $py = Find-Python312 }
if (-not $py) { Fail 'Python 3.12 not found. Close this window and start the setup again.' }
Info $py

Step '2/5  FFmpeg'
if (Has 'ffmpeg') { Info 'already installed' } else { Winget-Install 'Gyan.FFmpeg' }
if (-not (Has 'ffmpeg')) { Warn 'ffmpeg is not on PATH yet - it should work after restarting Windows.' }

Step '3/5  Deno (JavaScript runtime that yt-dlp needs for YouTube)'
if (Has 'deno') { Info 'already installed' } else { Winget-Install 'DenoLand.Deno' }
if (-not (Has 'deno')) { Warn 'deno is not on PATH yet - it should work after restarting Windows.' }

Step '4/5  Python environment (yt-dlp, PySide6)'
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
$Venv = Join-Path $AppDir 'venv'
$vpy = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $vpy)) {
    & $py -m venv $Venv
    if (-not (Test-Path $vpy)) { Fail 'Could not create the Python environment.' }
} else { Info 'already there' }
& $vpy -m pip install --upgrade --disable-pip-version-check -q pip
# PySide6-Addons brings QtMultimedia (the built-in video preview)
& $vpy -m pip install --upgrade --disable-pip-version-check "yt-dlp[default]" PySide6-Essentials PySide6-Addons
if ($LASTEXITCODE -ne 0) { Fail 'Packages could not be installed (check your internet connection and start the setup again).' }
& $vpy -c "import yt_dlp, PySide6.QtWidgets" 2>$null
if ($LASTEXITCODE -ne 0) { Fail 'yt-dlp / PySide6 are installed but cannot be imported.' }
& $vpy -c "import PySide6.QtMultimedia, PySide6.QtMultimediaWidgets" 2>$null
if ($LASTEXITCODE -ne 0) { Warn 'The video preview module could not be loaded - the app works, just without the player.' }

Step '5/5  App + shortcuts'
Copy-Item -Force (Join-Path $PSScriptRoot $Script) (Join-Path $AppDir $Script)
$icon = Join-Path $AppDir 'icon.ico'
if (Test-Path (Join-Path $PSScriptRoot 'icon.ico')) { Copy-Item -Force (Join-Path $PSScriptRoot 'icon.ico') $icon }
Copy-Item -Force (Join-Path $PSScriptRoot 'uninstall.ps1') (Join-Path $AppDir 'uninstall.ps1')
$target = Join-Path $AppDir $Script
$pyw = Join-Path $Venv 'Scripts\pythonw.exe'
$ws = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    foreach ($old in $OldNames) {   # shortcuts of the old "YT Clip" version
        $o = Join-Path $dir "$old.lnk"
        if (Test-Path $o) { Remove-Item -Force $o }
    }
    $lnkPath = Join-Path $dir "$AppName.lnk"
    $lnk = $ws.CreateShortcut($lnkPath)
    $lnk.TargetPath = $pyw
    $lnk.Arguments = "`"$target`""
    $lnk.WorkingDirectory = $AppDir
    $lnk.Description = 'Download YouTube videos as MP4, MP3 or GIF'
    if (Test-Path $icon) { $lnk.IconLocation = "$icon,0" } else { $lnk.IconLocation = "$pyw,0" }
    $lnk.Save()
    Set-ShortcutAppId $lnkPath 'tfrog.YouTubeDownloader'
    Info "Shortcut: $dir"
}

Write-Launcher $pyw $target
Register-Uninstall 'tfrog_YTClip' 'YouTube Downloader' $icon

Write-Host ''
Write-Host "Done! '$AppName' is on your desktop and in the Start menu." -ForegroundColor Cyan
Start-Process -FilePath $pyw -ArgumentList "`"$target`"" -WorkingDirectory $AppDir
if ($Exe) { Start-Sleep -Seconds 3 }
