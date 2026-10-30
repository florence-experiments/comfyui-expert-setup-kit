# Built by Florence for the community.
# ComfyUI Expert Setup Kit - Windows bootstrap. Downloads a private copy of Python (from nuget.org, SHA-256 checked),
# then runs the setup wizard. No admin rights needed. Nothing is installed system-wide.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Kit = $PSScriptRoot
$Runtime = Join-Path $Kit '.runtime'
$Py = Join-Path $Runtime 'python\python.exe'

$arch = $env:PROCESSOR_ARCHITECTURE
if ($arch -eq 'ARM64') {
    $Url = 'https://www.nuget.org/api/v2/package/pythonarm64/3.12.10'
    $Sha = 'e397423b13b1f1db294cd822b13a695b9f95193f2dc4572ff30dd5cd83b99c37'
} elseif ($arch -eq 'AMD64') {
    $Url = 'https://www.nuget.org/api/v2/package/python/3.12.10'
    $Sha = '0eb85c2dfccccf1b17352de4c397f69194035b7d37149eacc16f1147d93de3b8'
} else {
    Write-Host 'Sorry, ComfyUI Expert needs 64-bit Windows.'
    exit 1
}

if (-not (Test-Path $Py)) {
    Write-Host 'Downloading Python 3.12 for the installer (about 15 MB, from nuget.org)...'
    New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
    $Pkg = Join-Path $Runtime 'python-package.zip'
    Invoke-WebRequest -Uri $Url -OutFile $Pkg -UseBasicParsing
    $Got = (Get-FileHash -Algorithm SHA256 -Path $Pkg).Hash.ToLower()
    if ($Got -ne $Sha) {
        Remove-Item $Pkg -Force
        Write-Host 'The Python download did not match its expected SHA-256 - stopped for safety.'
        exit 1
    }
    Write-Host 'SHA-256 verified.'
    $Tmp = Join-Path $Runtime 'unpack'
    if (Test-Path $Tmp) { Remove-Item $Tmp -Recurse -Force }
    Expand-Archive -Path $Pkg -DestinationPath $Tmp
    Move-Item (Join-Path $Tmp 'tools') (Join-Path $Runtime 'python')
    Remove-Item $Tmp -Recurse -Force
    Remove-Item $Pkg -Force
}

$env:PYTHONPATH = $Kit
$env:PYTHONUTF8 = '1'
& $Py -m cesetup.main @args
exit $LASTEXITCODE
