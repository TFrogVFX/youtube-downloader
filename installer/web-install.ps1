# YouTube Downloader (by tfrog) - install straight from GitHub, without downloading an .exe
# (so no "uncommon download" warning in the browser and no "Windows protected your PC").
#
# Start -> type "PowerShell" -> Enter, then paste this line and press Enter:
#   irm https://raw.githubusercontent.com/TFrogVFX/youtube-downloader/main/installer/web-install.ps1 | iex
#
# It loads the app files of the newest version from this repository into a temporary folder, checks the app
# file against its checksum and runs the normal installer (installer/install.ps1).

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
