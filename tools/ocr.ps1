param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = "Stop"
# Windows 内置 OCR（Windows.Media.Ocr）读取截图中文字，作为 GUI 状态的客观文本证据。
# 用内存流加载，避免 StorageFile 在非 Store 进程下的访问限制。
Add-Type -AssemblyName System.Runtime.WindowsRuntime

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]

function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    try { $netTask.Wait(-1) | Out-Null }
    catch {
        $inner = $_.Exception.InnerException
        Write-Error ("Await 失败: " + ($(if ($inner) { $inner.Message } else { $_.Exception.Message })))
        throw
    }
    $netTask.Result
}

[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime] | Out-Null

$bytes = [System.IO.File]::ReadAllBytes($Path)
$ms = New-Object System.IO.MemoryStream
$ms.Write($bytes, 0, $bytes.Length)
$ms.Position = 0
$ras = [System.IO.WindowsRuntimeStreamExtensions]::AsRandomAccessStream($ms)

$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($ras)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage((New-Object Windows.Globalization.Language 'en-US'))
}
if ($null -eq $engine) { Write-Error "无可用 OCR 引擎"; exit 2 }

$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
Write-Output $result.Text
