$ErrorActionPreference = "Stop"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Error "Python is required to run the installer. Install Python 3.11+ and retry."
}

python "installer/main.py" @Args
