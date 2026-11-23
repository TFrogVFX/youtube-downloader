# YouTube Downloader (by tfrog) - install straight from GitHub, without downloading an .exe
# (so no "uncommon download" warning in the browser and no "Windows protected your PC").
#
# Start -> type "PowerShell" -> Enter, then paste this line and press Enter:
#   irm https://raw.githubusercontent.com/TFrogVFX/youtube-downloader/main/installer/web-install.ps1 | iex
#
# It loads the setup (setup/YouTube-Downloader.exe) of the newest version from this repository, checks it against
# its checksum and opens its setup window. If that doesn't work: the app files + the PowerShell installer.

& {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $repo = 'TFrogVFX/youtube-downloader'

    Write-Host ''
    Write-Host 'YouTube Downloader - loading the newest version from GitHub ...' -ForegroundColor Green

    # the newest commit's own address (the address of "main" can lag a few minutes behind after an update)
    $base = "https://raw.githubusercontent.com/$repo/main/"
    try {
        $sha = Invoke-RestMethod -UseBasicParsing -Headers @{ Accept = 'application/vnd.github.sha' } `
            -Uri "https://api.github.com/repos/$repo/commits/main"
        $sha = "$sha".Trim()
        if ($sha -match '^[0-9a-f]{40}$') { $base = "https://raw.githubusercontent.com/$repo/$sha/" }
    } catch { }

    # the setup window (YouTube-Downloader.exe from this repository) - loaded here, so Windows shows no warning
    try {
        $info = Invoke-RestMethod -UseBasicParsing -Uri ($base + 'version.json')
        if ($info.setup_sha256) {
            $exe = Join-Path $env:TEMP 'YouTube-Downloader-Setup.exe'
            Invoke-WebRequest -UseBasicParsing -Uri ($base + 'setup/YouTube-Downloader.exe') -OutFile $exe
            $h = (Get-FileHash -Algorithm SHA256 $exe).Hash.ToLower()
            if ($h -eq $info.setup_sha256) {
                Write-Host "   version $($info.version) loaded, checksum OK - the setup window opens now." -ForegroundColor DarkGray
                Start-Process -FilePath $exe -ArgumentList '/repair'
                Write-Host ''
                Write-Host 'You can close this PowerShell window.' -ForegroundColor Green
                return
            }
            Remove-Item -Force $exe -ErrorAction SilentlyContinue
            Write-Host '   setup file damaged - using the PowerShell setup instead.' -ForegroundColor Yellow
        }
    } catch {
        Write-Host '   setup window not available - using the PowerShell setup instead.' -ForegroundColor Yellow
    }

    $tmp = Join-Path $env:TEMP ('ytd-setup-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        $files = @(
            @('installer/install.ps1', 'install.ps1'),
            @('installer/uninstall.ps1', 'uninstall.ps1'),
            @('tfrog_ytclip.pyw', 'tfrog_ytclip.pyw'),
            @('icon.ico', 'icon.ico')
        )
        foreach ($f in $files) {
            Invoke-WebRequest -UseBasicParsing -Uri ($base + $f[0]) -OutFile (Join-Path $tmp $f[1])
        }
        $info = Invoke-RestMethod -UseBasicParsing -Uri ($base + 'version.json')
        $hash = (Get-FileHash -Algorithm SHA256 (Join-Path $tmp 'tfrog_ytclip.pyw')).Hash.ToLower()
        if ($info.sha256 -and $hash -ne $info.sha256) {
            throw 'The download is damaged (checksum) - please run the line again in a few minutes.'
        }
        Write-Host "   version $($info.version) loaded, checksum OK" -ForegroundColor DarkGray
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $tmp 'install.ps1')
    } catch {
        Write-Host ''
        Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    } finally {
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    }
}
