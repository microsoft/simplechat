// Test the improved ASCII conversion with proper header handling
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

function convertASCIIDashTableToMarkdown(content) {
  console.log('🔧 Converting ASCII dash tables to markdown format');
  
  try {
    const lines = content.split('\n');
    const dashLineIndices = [];
    
    // Find all lines that are primarily dash characters (table boundaries)
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line.includes('─') && line.replace(/[─\s]/g, '').length === 0 && line.length > 10) {
        dashLineIndices.push(i);
      }
    }
    
    console.log('Found dash line boundaries at:', dashLineIndices);
    
    // Process each complete table (from first dash to last dash in a sequence)
    let processedContent = content;
    
    if (dashLineIndices.length >= 2) {
      // For this test, we'll just process the first complete table
      const firstDashIdx = dashLineIndices[0];
      const lastDashIdx = dashLineIndices[dashLineIndices.length - 1];
      
      console.log(`Processing complete ASCII table from line ${firstDashIdx} to ${lastDashIdx}`);
      
      // Extract header and data lines
      const headerLine = lines[firstDashIdx + 1]; // Line immediately after first dash
      
      if (headerLine && headerLine.trim()) {
        // Process header
        const headerCells = headerLine.split(/\s{2,}/)
          .map(cell => cell.trim())
          .filter(cell => cell !== '');
        
        // Process data rows (skip intermediate dash lines)
        const processedDataRows = [];
        for (let lineIdx = firstDashIdx + 2; lineIdx < lastDashIdx; lineIdx++) {
          const line = lines[lineIdx];
          // Skip dash separator lines
          if (line.includes('─') && line.replace(/[─\s]/g, '').length === 0) {
            continue;
          }
          
          if (line.trim()) {
            const dataCells = line.split(/\s{2,}/)
              .map(cell => cell.trim())
              .filter(cell => cell !== '');
            
            if (dataCells.length > 1) {
              processedDataRows.push(dataCells);
            }
          }
        }
        
        console.log('Processed header:', headerCells);
        console.log('Processed data rows:', processedDataRows);
        
        if (headerCells.length > 1 && processedDataRows.length > 0) {
          console.log(`✅ Converting ASCII table: ${headerCells.length} columns, ${processedDataRows.length} rows`);
          
          // Build markdown table
          let markdownTable = '\n\n';
          markdownTable += '| ' + headerCells.join(' | ') + ' |\n';
          markdownTable += '|' + headerCells.map(() => '---').join('|') + '|\n';
          
          for (const row of processedDataRows) {
            // Ensure we have the same number of columns as header
            while (row.length < headerCells.length) {
              row.push('—');
            }
            // Trim extra columns if any
            const trimmedRow = row.slice(0, headerCells.length);
            markdownTable += '| ' + trimmedRow.join(' | ') + ' |\n';
          }
          markdownTable += '\n';
          
          // Replace the original table section with markdown
          const tableSection = lines.slice(firstDashIdx, lastDashIdx + 1);
          const originalTableText = tableSection.join('\n');
          processedContent = processedContent.replace(originalTableText, markdownTable);
          
          console.log('✅ ASCII table successfully converted to markdown');
          return processedContent;
        }
      }
    }
    
    return processedContent;
    
  } catch (error) {
    console.error('Error converting ASCII dash table:', error);
    return content;
  }
}

console.log("=== TESTING IMPROVED ASCII CONVERSION WITH HEADER ===");
const result = convertASCIIDashTableToMarkdown(testContent);
console.log("\n=== RESULT ===");
console.log(result);

const hasMarkdownTable = result.includes('| AGENCY |') && result.includes('---');
console.log("\nContains proper header:", hasMarkdownTable);

if (hasMarkdownTable) {
    console.log("✅ SUCCESS: ASCII table with header converted correctly!");
} else {
    console.log("❌ FAILED: Header not found in result");
}