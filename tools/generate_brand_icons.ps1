[CmdletBinding(DefaultParameterSetName = 'Monogram')]
param(
    [Parameter(Mandatory)] [string] $OutputPng,
    [string] $OutputIco,
    [int] $Canvas = 512,

    [Parameter(Mandatory, ParameterSetName = 'Monogram')] [int] $CodePoint,
    [Parameter(Mandatory, ParameterSetName = 'Monogram')] [string] $DiscColor,
    [Parameter(Mandatory, ParameterSetName = 'Monogram')] [string] $GlyphColor,
    [Parameter(ParameterSetName = 'Monogram')] [double] $GlyphHeightRatio = 0.5,
    [Parameter(ParameterSetName = 'Monogram')] [double] $GlyphWidthRatio = 0.62,
    [Parameter(ParameterSetName = 'Monogram')] [int] $DiscMargin = 8,

    [Parameter(Mandatory, ParameterSetName = 'Image')] [string] $Source,
    [Parameter(Mandatory, ParameterSetName = 'Image')] [int] $FitX,
    [Parameter(Mandatory, ParameterSetName = 'Image')] [int] $FitY,
    [Parameter(Mandatory, ParameterSetName = 'Image')] [int] $FitWidth,
    [Parameter(Mandatory, ParameterSetName = 'Image')] [int] $FitHeight
)

# A drawing tool only: the caller (jarvis.core.brand_render) decides every
# colour, ratio and rectangle. Exit code 2 means the source image could not be
# decoded; any other failure exits 1 with the message on stderr.
$ErrorActionPreference = "Stop"
# stderr is read by Python as UTF-8, not the console OEM code page; best effort,
# because setting it throws when the process has no console handle.
try { [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false) } catch { $null = $_ }
Add-Type -AssemblyName System.Drawing

function Set-HighQuality([Drawing.Graphics] $graphics) {
    $graphics.SmoothingMode = [Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.CompositingQuality = [Drawing.Drawing2D.CompositingQuality]::HighQuality
    $graphics.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.PixelOffsetMode = [Drawing.Drawing2D.PixelOffsetMode]::HighQuality
}

function Add-Monogram([Drawing.Graphics] $graphics) {
    $diameter = $Canvas - 2 * $DiscMargin
    $discBrush = [Drawing.SolidBrush]::new([Drawing.ColorTranslator]::FromHtml($DiscColor))
    $glyphBrush = [Drawing.SolidBrush]::new([Drawing.ColorTranslator]::FromHtml($GlyphColor))
    $family = [Drawing.FontFamily]::new("Segoe UI Semibold")
    $path = [Drawing.Drawing2D.GraphicsPath]::new()
    $matrix = [Drawing.Drawing2D.Matrix]::new()
    try {
        $graphics.FillEllipse($discBrush, $DiscMargin, $DiscMargin, $diameter, $diameter)
        $path.AddString(
            [char]::ConvertFromUtf32($CodePoint), $family, [int][Drawing.FontStyle]::Regular,
            100.0, [Drawing.PointF]::new(0, 0), [Drawing.StringFormat]::GenericTypographic)
        $bounds = $path.GetBounds()
        $scale = [Math]::Min(
            $GlyphHeightRatio * $diameter / $bounds.Height,
            $GlyphWidthRatio * $diameter / $bounds.Width)
        $matrix.Translate(-($bounds.X + $bounds.Width / 2), -($bounds.Y + $bounds.Height / 2))
        $matrix.Scale($scale, $scale, [Drawing.Drawing2D.MatrixOrder]::Append)
        $matrix.Translate($Canvas / 2.0, $Canvas / 2.0, [Drawing.Drawing2D.MatrixOrder]::Append)
        $path.Transform($matrix)
        $graphics.FillPath($glyphBrush, $path)
    } finally {
        $matrix.Dispose(); $path.Dispose(); $family.Dispose()
        $glyphBrush.Dispose(); $discBrush.Dispose()
    }
}

function Add-FittedImage([Drawing.Graphics] $graphics) {
    try {
        $image = [Drawing.Image]::FromFile((Resolve-Path -LiteralPath $Source).Path)
    } catch {
        [Console]::Error.WriteLine("The image could not be decoded: $($_.Exception.Message)")
        exit 2
    }
    $attributes = [Drawing.Imaging.ImageAttributes]::new()
    try {
        $attributes.SetWrapMode([Drawing.Drawing2D.WrapMode]::TileFlipXY)
        $graphics.CompositingMode = [Drawing.Drawing2D.CompositingMode]::SourceCopy
        $destination = [Drawing.Rectangle]::new($FitX, $FitY, $FitWidth, $FitHeight)
        $graphics.DrawImage(
            $image, $destination, 0, 0, $image.Width, $image.Height,
            [Drawing.GraphicsUnit]::Pixel, $attributes)
    } finally {
        $attributes.Dispose(); $image.Dispose()
    }
}

try {
    $bitmap = [Drawing.Bitmap]::new($Canvas, $Canvas, [Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.Clear([Drawing.Color]::Transparent)
        Set-HighQuality $graphics
        if ($PSCmdlet.ParameterSetName -eq 'Monogram') { Add-Monogram $graphics } else { Add-FittedImage $graphics }
    } finally {
        $graphics.Dispose()
    }
    try {
        $bitmap.Save([IO.Path]::GetFullPath($OutputPng), [Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $bitmap.Dispose()
    }
    if ($OutputIco) {
        & (Join-Path $PSScriptRoot "build_launcher_icon.ps1") -Source $OutputPng -Output $OutputIco | Out-Null
    }
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
