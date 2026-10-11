$ErrorActionPreference = 'Stop'
$sampleWorkbook = (Resolve-Path "$PSScriptRoot\..\output\playwright\demo.xlsx").Path
$excelApp = $null
$workbook = $null
try {
    $excelApp = New-Object -ComObject Excel.Application
    $excelApp.Visible = $false
    $excelApp.DisplayAlerts = $false
    $excelApp.AutomationSecurity = 3
    $workbook = $excelApp.Workbooks.Open($sampleWorkbook, 0, $true)
    $sheet = $workbook.Worksheets.Item(1)
    $literal = $sheet.Cells.Item(4, 2)
    if ($literal.Value2 -ne '=00123' -or $literal.HasFormula) { throw 'Literal prefix was not preserved in Excel' }
    if ($sheet.Cells.Item(3, 2).Value2 -ne '00007') { throw 'Leading zeros were not preserved' }
    if (-not $sheet.Cells.Item(1, 1).MergeCells) { throw 'Merged header missing' }
    if ($workbook.Worksheets.Count -ne 4) { throw 'Evidence worksheets missing' }
    Write-Output 'Excel passed: opens without repair, literal =00123, 00007, merged headers and evidence sheets.'
} finally {
    if ($workbook) { $workbook.Close($false); [Runtime.InteropServices.Marshal]::FinalReleaseComObject($workbook) | Out-Null }
    if ($excelApp) { $excelApp.Quit(); [Runtime.InteropServices.Marshal]::FinalReleaseComObject($excelApp) | Out-Null }
}
