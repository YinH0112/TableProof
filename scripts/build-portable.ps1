param([string]$NodeDirectory = "$PSScriptRoot\..\.tools\node-v24.21.0-win-x64")
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location -LiteralPath $projectRoot
if (Test-Path -LiteralPath $NodeDirectory) { $env:Path = "$( (Resolve-Path -LiteralPath $NodeDirectory).Path );$env:Path" }
& npm.cmd --prefix frontend ci
if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
& npm.cmd --prefix frontend run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
& uv sync --frozen --cache-dir .tools\uv-cache
if ($LASTEXITCODE -ne 0) { throw 'Python dependency install failed' }
& .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir --name TableProof --paths src --collect-all pdfplumber --collect-all pdfminer --collect-all pypdfium2 --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on --add-data 'frontend/dist;frontend/dist' --add-data 'samples/demo.pdf;samples' scripts\portable_entry.py
if ($LASTEXITCODE -ne 0) { throw 'Portable build failed' }
Copy-Item -LiteralPath LICENSE,README.md,README.zh-CN.md,THIRD_PARTY_NOTICES.md,CONTRIBUTING.md -Destination dist\TableProof
Copy-Item -LiteralPath docs -Destination dist\TableProof -Recurse -Force
Copy-Item -LiteralPath scripts\start-portable.cmd -Destination dist\TableProof\Start.cmd
& .venv\Scripts\python.exe scripts\collect_licenses.py
if ($LASTEXITCODE -ne 0) { throw 'License collection failed' }
Compress-Archive -Path dist\TableProof -DestinationPath dist\TableProof-0.1.0-windows-x64.zip -Force
Write-Output "Portable package: $projectRoot\dist\TableProof-0.1.0-windows-x64.zip"
