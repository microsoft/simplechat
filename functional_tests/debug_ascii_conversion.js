// Debug ASCII Dash Table Conversion
const testContent = `─────────────────────────────────────────────────────────────────
 AGENCY          MONTH/YEAR   FORECAST        ACTUAL         VARIANCE  
─────────────────────────────────────────────────────────────────
 IRS             Apr 2025     $4.02B          $3.86B         -$0.16B   
 IRS             May 2025     $4.13B          $4.23B         +$0.11B   
 IRS             Jun 2025     $4.14B          $3.99B         -$0.14B   
 CMS             Apr–Jun 2025 —               —              —          
─────────────────────────────────────────────────────────────────`;

console.log("=== DEBUGGING ASCII DASH TABLE CONVERSION ===");
console.log("Original content:");
console.log(testContent);
console.log("\n=== STEP 1: Test Regex Pattern ===");

// Current pattern
const currentPattern = /─{10,}[^\n]*\n[\s\S]*?─{10,}/g;
const matches = testContent.match(currentPattern);
console.log("Current pattern matches:", matches);
console.log("Match count:", matches ? matches.length : 0);

if (matches) {
    console.log("\n=== STEP 2: Parse First Match ===");
    const match = matches[0];
    console.log("First match:");
    console.log(match);
    
    console.log("\n=== STEP 3: Split into Lines ===");
    const lines = match.split('\n');
    lines.forEach((line, index) => {
        console.log(`Line ${index}:`, JSON.stringify(line));
    });
    
    console.log("\n=== STEP 4: Process Each Line ===");
    const dataLines = [];
    let headerLine = null;
    
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        console.log(`\nProcessing line ${i}: "${line}"`);
        
        // Check if it's a separator line
        const isDashLine = line.includes('─') && line.replace(/[─\s]/g, '').length === 0;
        console.log("Is dash line:", isDashLine);
        
        if (isDashLine) {
            console.log("Skipping separator line");
            continue;
        }
        
        // Check if it has content
        if (line.trim() && !line.match(/^─+$/)) {
            console.log("Line has content, splitting by spaces...");
            
            // Split by multiple spaces
            const cells = line.split(/\s{2,}/)
                .map(cell => cell.trim())
                .filter(cell => cell !== '');
            
            console.log("Split cells:", cells);
            console.log("Cell count:", cells.length);
            
            if (cells.length > 1) {
                if (!headerLine) {
                    headerLine = cells;
                    console.log("Set as header:", headerLine);
                } else {
                    dataLines.push(cells);
                    console.log("Added as data row:", cells);
                }
            }
        } else {
            console.log("Line skipped (empty or dash-only)");
        }
    }
    
    console.log("\n=== STEP 5: Final Results ===");
    console.log("Header line:", headerLine);
    console.log("Data lines:", dataLines);
    console.log("Data line count:", dataLines.length);
    
    if (headerLine && dataLines.length > 0) {
        console.log("\n=== STEP 6: Generate Markdown ===");
        let markdownTable = '\n\n';
        markdownTable += '| ' + headerLine.join(' | ') + ' |\n';
        markdownTable += '|' + headerLine.map(() => '---').join('|') + '|\n';
        
        for (const row of dataLines) {
            while (row.length < headerLine.length) {
                row.push('—');
            }
            markdownTable += '| ' + row.join(' | ') + ' |\n';
        }
        markdownTable += '\n';
        
        console.log("Generated markdown:");
        console.log(markdownTable);
    } else {
        console.log("❌ CONVERSION FAILED - No valid header/data found");
    }
}

console.log("\n=== ALTERNATIVE APPROACH TESTING ===");

// Let's try a different approach - split by lines first, then identify table sections
const allLines = testContent.split('\n');
console.log("All lines:");
allLines.forEach((line, index) => {
    const isDash = /^─+$/.test(line.trim());
    const hasContent = line.trim() && !isDash;
    console.log(`${index}: ${isDash ? '[DASH]' : hasContent ? '[DATA]' : '[EMPTY]'} "${line}"`);
});