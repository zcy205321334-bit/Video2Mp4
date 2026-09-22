param(
    [Parameter(Mandatory = $true)][string]$Out,
    [int]$X = -1, [int]$Y = -1, [int]$W = 0, [int]$H = 0
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$s = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$full = New-Object System.Drawing.Bitmap($s.Width, $s.Height)
$g = [System.Drawing.Graphics]::FromImage($full)
$g.CopyFromScreen($s.Location, [System.Drawing.Point]::Empty, $s.Size)
if ($W -gt 0 -and $H -gt 0) {
    $crop = New-Object System.Drawing.Bitmap($W, $H)
    $g2 = [System.Drawing.Graphics]::FromImage($crop)
    $dstRect = New-Object System.Drawing.Rectangle(0, 0, $W, $H)
    $srcRect = New-Object System.Drawing.Rectangle($X, $Y, $W, $H)
    $g2.DrawImage($full, $dstRect, $srcRect, [System.Drawing.GraphicsUnit]::Pixel)
    $crop.Save($Out)
    $g2.Dispose(); $crop.Dispose()
}
else {
    $full.Save($Out)
}
$g.Dispose(); $full.Dispose()
Write-Output $Out
