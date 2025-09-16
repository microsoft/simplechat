// Test the improved ASCII conversion function
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
  // Improved pattern to match complete ASCII tables with em-dash separators
  const asciiTablePattern = /─{10,}[\s\S]*?─{10,}/g;
  
  return content.replace(asciiTablePattern, (match) => {
    console.log('🔧 Converting ASCII dash table to markdown format');
    console.log('Table match found:', match.substring(0, 100) + '...');
    
    try {
      const lines = match.split('\n');
      const dataLines = [];
      let headerLine = null;
      
      console.log(`Processing ${lines.length} lines from ASCII table`);
      
      // Extract data from ASCII table
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        
        // Skip separator lines (lines that are only dashes and spaces)
        if (line.includes('─') && line.replace(/[─\s]/g, '').length === 0) {
          console.log(`Line ${i}: Skipping separator line`);
          continue;
        }
        
        // Process data lines (lines with actual content)
        if (line.trim() && !line.match(/^─+$/)) {
          // Split by multiple spaces (assuming columns are separated by multiple spaces)
          const cells = line.split(/\s{2,}/)
            .map(cell => cell.trim())
            .filter(cell => cell !== '');
          
          console.log(`Line ${i}: Found ${cells.length} cells:`, cells);
          
          if (cells.length > 1) {
            if (!headerLine) {
              headerLine = cells;
              console.log('ASCII Header row set:', headerLine);
            } else {
              dataLines.push(cells);
              console.log('ASCII Data row added:', cells);
            }
          }
        }
      }
      
      console.log(`Final extraction: Header=${headerLine ? headerLine.length : 0} cols, ${dataLines.length} data rows`);
      
      if (headerLine && dataLines.length > 0) {
        console.log(`✅ Successfully extracted ASCII table: ${headerLine.length} columns, ${dataLines.length} rows`);
        
        // Build markdown table
        let markdownTable = '\n\n';
        
        // Header row
        markdownTable += '| ' + headerLine.join(' | ') + ' |\n';
        
        // Separator row
        markdownTable += '|' + headerLine.map(() => '---').join('|') + '|\n';
        
        // Data rows (limit to first 10 for display)
        const displayRows = dataLines.slice(0, 10);
        for (const row of displayRows) {
          // Ensure we have the same number of columns as header
          while (row.length < headerLine.length) {
            row.push('—');
          }
          markdownTable += '| ' + row.join(' | ') + ' |\n';
        }
        
        if (dataLines.length > 10) {
          markdownTable += '\n*Showing first 10 of ' + dataLines.length + ' total rows*\n';
        }
        
        markdownTable += '\n';
        console.log('✅ Generated markdown table:', markdownTable.length, 'characters');
        return markdownTable;
      } else {
        console.log('❌ ASCII table conversion failed: insufficient data');
      }
    } catch (error) {
      console.error('Error converting ASCII dash table:', error);
    }
    
    // If conversion fails, return original content
    return match;
  });
}

console.log("=== TESTING IMPROVED ASCII CONVERSION ===");
const result = convertASCIIDashTableToMarkdown(testContent);
console.log("\n=== CONVERSION RESULT ===");
console.log(result);

console.log("\n=== CHECKING FOR MARKDOWN TABLE ===");
const hasMarkdownTable = result.includes('|') && result.includes('---');
console.log("Contains markdown table syntax:", hasMarkdownTable);

if (hasMarkdownTable) {
    console.log("✅ SUCCESS: ASCII table converted to markdown!");
} else {
    console.log("❌ FAILED: No markdown table found in result");
}