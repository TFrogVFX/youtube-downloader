# YouTube Downloader (by tfrog) - uninstaller (Windows Settings > Apps, or uninstall.bat)

$AppName = 'YouTube Downloader'
$AppDir  = Join-Path $env:LOCALAPPDATA 'tfrog_ytclip'
$Script  = 'tfrog_ytclip.pyw'
$UninstKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\tfrog_YTClip'

function Done([int]$code) { Write-Host ''; Read-Host 'Press Enter to close' | Out-Null; exit $code }

Write-Host "YouTube Downloader - Uninstall" -ForegroundColor Cyan
Write-Host ''
Write-Host 'This removes the YouTube Downloader: the app, its Python environment and its settings.'
Write-Host 'Your downloaded files are NOT touched. Python, FFmpeg and Deno stay installed.'
Write-Host ''
$a = Read-Host 'Continue? (y/n)'
if ($a -notmatch '^(y|yes|j|ja)$') { Write-Host 'Nothing removed.'; Done 0 }

$running = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*$Script*" }
if ($running) {
    Write-Host "$AppName is still running - please close it and try again." -ForegroundColor Yellow
    Done 1
}

foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    foreach ($n in @($AppName, 'tfrog YT Clip')) {
        $lnk = Join-Path $dir "$n.lnk"
        if (Test-Path $lnk) { Remove-Item -Force $lnk; Write-Host "   removed $lnk" -ForegroundColor DarkGray }
    }
}
Remove-Item -Recurse -Force $UninstKey -ErrorAction SilentlyContinue
if (Test-Path $AppDir) {
    Remove-Item -Recurse -Force $AppDir -ErrorAction SilentlyContinue
    if (Test-Path $AppDir) {
        Write-Host "Could not delete everything in $AppDir - please delete it manually." -ForegroundColor Yellow
        Done 1
    }
    Write-Host "   removed $AppDir" -ForegroundColor DarkGray
}
Write-Host ''
Write-Host "$AppName has been removed." -ForegroundColor Cyan
Done 0
