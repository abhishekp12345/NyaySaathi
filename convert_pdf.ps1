try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $docPath = "C:\Users\Asus\Desktop\KUKU\Assignment_q2\paisa-wapas\SOLUTION_DOC.docx"
    $pdfPath = "C:\Users\Asus\Desktop\KUKU\Assignment_q2\paisa-wapas\SOLUTION_DOC.pdf"
    $doc = $word.Documents.Open($docPath)
    $doc.SaveAs([ref]$pdfPath, [ref]17)
    $doc.Close()
    $word.Quit()
    Write-Host "SUCCESS: Generated SOLUTION_DOC.pdf"
} catch {
    Write-Host "Word COM error: $_"
}
