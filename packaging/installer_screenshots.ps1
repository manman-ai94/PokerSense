# Screenshots of the installer's pages on a Windows runner (best effort).
# Runs the installer interactively, captures each page, presses Enter to go on
# and closes it on the last page without starting the program.
param(
  [Parameter(Mandatory = $true)][string]$Installer,
  [Parameter(Mandatory = $true)][string]$OutDir
)
Add-Type -AssemblyName System.Windows.Forms, System.Drawing, Microsoft.VisualBasic
New-Item -ItemType Directory -Force $OutDir | Out-Null

function Save-Screen([string]$Name) {
  $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
  $bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
  $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
  $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
  $bitmap.Save((Join-Path $OutDir $Name), [System.Drawing.Imaging.ImageFormat]::Png)
  $graphics.Dispose(); $bitmap.Dispose()
}

function Focus-Setup {
  $window = Get-Process | Where-Object { $_.MainWindowTitle -like "*PokerSense*" } |
    Select-Object -First 1
  if ($window) { [Microsoft.VisualBasic.Interaction]::AppActivate($window.Id) | Out-Null }
}

$process = Start-Process $Installer -PassThru
Start-Sleep -Seconds 8
Focus-Setup
Save-Screen "installer-1-ready.png"
[System.Windows.Forms.SendKeys]::SendWait("{ENTER}")       # Install
Start-Sleep -Seconds 25
Focus-Setup
Save-Screen "installer-2-finished.png"
# Untick "launch the program" (space on the focused checkbox would toggle it,
# but focus is not guaranteed): close the wizard instead; files are in place.
Get-Process | Where-Object { $_.ProcessName -like "PokerSense-AA-Setup*" } |
  Stop-Process -Force -ErrorAction SilentlyContinue
Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
Get-ChildItem $OutDir | Select-Object Name, Length
