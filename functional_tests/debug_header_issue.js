// Debug the current table processing logic
const testContent = `Below is the available Q2 2025 comparison for the IRS and CMS:

─────────────────────────────────────────────────────────────────
 AGENCY          MONTH/YEAR   FORECAST        ACTUAL         VARIANCE  
─────────────────────────────────────────────────────────────────
 IRS             Apr 2025     $4.02B          $3.86B         -$0.16B   
 IRS             May 2025     $4.13B          $4.23B         +$0.11B   
 IRS             Jun 2025     $4.14B          $3.99B         -$0.14B   
 CMS             Apr–Jun 2025 —               —              —          
─────────────────────────────────────────────────────────────────

This data shows the quarterly comparison.`;

console.log("=== DEBUGGING CURRENT LOGIC ===");
const lines = testContent.split('\n');
const dashLineIndices = [];

// Find dash lines
for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.includes('─') && line.replace(/[─\s]/g, '').length === 0 && line.length > 10) {
        dashLineIndices.push(i);
    }
}

console.log('Lines:');
lines.forEach((line, i) => {
    console.log(`${i}: "${line}"`);
});

console.log('\nDash line indices:', dashLineIndices);

// Check current pairing logic
console.log('\nCurrent pairing logic results:');
for (let i = dashLineIndices.length - 1; i >= 0; i -= 2) {
    if (i >= 1) {
        const startIdx = dashLineIndices[i - 1];
        const endIdx = dashLineIndices[i];
        console.log(`Pair: ${startIdx} to ${endIdx}`);
        console.log(`Header line (${startIdx + 1}): "${lines[startIdx + 1]}"`);
        console.log(`Data lines (${startIdx + 2} to ${endIdx - 1}):`);
        for (let j = startIdx + 2; j < endIdx; j++) {
            console.log(`  ${j}: "${lines[j]}"`);
        }
    }
}

console.log('\n=== BETTER APPROACH ===');
// Better approach: Find the complete table (first dash to last dash)
if (dashLineIndices.length >= 2) {
    const firstDash = dashLineIndices[0];
    const lastDash = dashLineIndices[dashLineIndices.length - 1];
    
    console.log(`Complete table from ${firstDash} to ${lastDash}`);
    console.log(`Header line (${firstDash + 1}): "${lines[firstDash + 1]}"`);
    console.log('Data lines:');
    for (let i = firstDash + 2; i < lastDash; i++) {
        if (lines[i].trim()) {
            console.log(`  ${i}: "${lines[i]}"`);
        }
    }
    
    // Process header
    const headerLine = lines[firstDash + 1];
    const headerCells = headerLine.split(/\s{2,}/)
        .map(cell => cell.trim())
        .filter(cell => cell !== '');
    
    console.log('Header cells:', headerCells);
    
    // Process data
    const dataRows = [];
    for (let i = firstDash + 2; i < lastDash; i++) {
        const line = lines[i];
        if (line.trim()) {
            const cells = line.split(/\s{2,}/)
                .map(cell => cell.trim())
                .filter(cell => cell !== '');
            if (cells.length > 1) {
                dataRows.push(cells);
            }
        }
    }
    
    console.log('Data rows:', dataRows);
    
    if (headerCells.length > 1 && dataRows.length > 0) {
        console.log('✅ This approach works! Building markdown...');
        let markdownTable = '\n\n';
        markdownTable += '| ' + headerCells.join(' | ') + ' |\n';
        markdownTable += '|' + headerCells.map(() => '---').join('|') + '|\n';
        
        for (const row of dataRows) {
            while (row.length < headerCells.length) {
                row.push('—');
            }
            const trimmedRow = row.slice(0, headerCells.length);
            markdownTable += '| ' + trimmedRow.join(' | ') + ' |\n';
        }
        markdownTable += '\n';
        
        console.log('Generated markdown:');
        console.log(markdownTable);
    }
}