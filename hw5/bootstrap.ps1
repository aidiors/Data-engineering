$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
New-Item -ItemType Directory -Force .runtime | Out-Null
if (-not (Test-Path -LiteralPath .venv\Scripts\python.exe)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'venv failed' }
}
& .venv\Scripts\python.exe -m pip install -r requirements-local.txt
if ($LASTEXITCODE -ne 0) { throw 'pip failed' }
if (-not (Test-Path -LiteralPath .runtime\qemu\qemu-system-x86_64.exe)) {
    Invoke-WebRequest 'https://qemu.weilnetz.de/w64/qemu-w64-setup-20260811.exe' -OutFile .runtime\qemu-setup.exe
    $actual = (Get-FileHash -LiteralPath .runtime\qemu-setup.exe -Algorithm SHA512).Hash
    if ($actual -ne '5BCF9EED634E8575A37B74F445AF41A2FE4106DA512D0C30C368301D4C105037FDFAB40A5287367A28A957624CDDEBBC8C07E16C88AB6634F554CDF3D16BF543') { throw 'QEMU hash mismatch' }
    $extractor = Get-Command 7z -ErrorAction SilentlyContinue
    $extractorPath = if ($extractor) { $extractor.Source } else { Join-Path $env:USERPROFILE 'scoop\apps\7zip\current\7z.exe' }
    if (-not (Test-Path -LiteralPath $extractorPath)) { throw '7-Zip is required' }
    & $extractorPath x .runtime\qemu-setup.exe '-o.runtime\qemu' -y -bso0 -bsp0
    if ($LASTEXITCODE -ne 0) { throw 'QEMU extraction failed' }
}
if (-not (Test-Path -LiteralPath .runtime\debian.qcow2)) {
    Invoke-WebRequest 'https://cloud.debian.org/images/cloud/trixie/latest/debian-13-genericcloud-amd64.qcow2' -OutFile .runtime\debian.qcow2
    & .runtime\qemu\qemu-img.exe resize .runtime\debian.qcow2 24G
    if ($LASTEXITCODE -ne 0) { throw 'Disk preparation failed' }
}
& .venv\Scripts\python.exe src\local_cluster.py start
if ($LASTEXITCODE -ne 0) { throw 'Local cluster start failed' }
