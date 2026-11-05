$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
New-Item -ItemType Directory -Force .runtime | Out-Null
if (-not (Test-Path -LiteralPath .venv\Scripts\python.exe)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'venv failed' }
}
& .venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'pip failed' }
$archive = Join-Path $PSScriptRoot '.runtime\zookeeper.tar.gz'
if (-not (Test-Path -LiteralPath .runtime\apache-zookeeper-3.9.6-bin)) {
    Invoke-WebRequest -Uri 'https://repo.huaweicloud.com/apache/zookeeper/zookeeper-3.9.6/apache-zookeeper-3.9.6-bin.tar.gz' -OutFile $archive
    $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
    if ($actual -ne '6034C9B7B92E60B28AC1F36639F704AF98F6D09E74B081664534D3004621D176') { throw 'ZooKeeper archive hash mismatch' }
    tar -xzf $archive -C .runtime
    if ($LASTEXITCODE -ne 0) { throw 'tar failed' }
}
$javaDirectory = Get-ChildItem -LiteralPath .runtime -Directory -Filter 'jdk-17*' | Select-Object -First 1
if (-not $javaDirectory) {
    Invoke-WebRequest -Uri 'https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse' -OutFile .runtime\jdk17.zip
    Expand-Archive -LiteralPath .runtime\jdk17.zip -DestinationPath .runtime -Force
    $javaDirectory = Get-ChildItem -LiteralPath .runtime -Directory -Filter 'jdk-17*' | Select-Object -First 1
}
$env:JAVA_HOME = $javaDirectory.FullName
@{ java_home = $env:JAVA_HOME; distribution = (Join-Path $PSScriptRoot '.runtime\apache-zookeeper-3.9.6-bin') } | ConvertTo-Json | Set-Content -LiteralPath .runtime\environment.json -Encoding utf8
& .venv\Scripts\python.exe -m src.cluster setup
if ($LASTEXITCODE -ne 0) { throw 'ensemble setup failed' }
& "$env:JAVA_HOME\bin\java.exe" -version
