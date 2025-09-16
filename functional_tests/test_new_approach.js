// Better approach to match complete ASCII tables
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
  // Step 1: Find all potential ASCII table boundaries
  const lines = content.split('\n');
  const dashLineIndices = [];
  
  // Find all lines that are primarily dash characters
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.includes('─') && line.replace(/[─\s]/g, '').length === 0 && line.length > 10) {
      dashLineIndices.push(i);
    }
  }
  
  console.log('Found dash lines at indices:', dashLineIndices);
  
  // Step 2: For each pair of dash lines, try to extract a table
  for (let i = 0; i < dashLineIndices.length - 1; i++) {
    const startIdx = dashLineIndices[i];
    const endIdx = dashLineIndices[i + 1];
    
    console.log(`Checking potential table from line ${startIdx} to ${endIdx}`);
    
    // Extract lines between dash separators
    const tableLines = lines.slice(startIdx + 1, endIdx);
    console.log('Table content lines:', tableLines);
    
    if (tableLines.length > 0) {
      const dataLines = [];
      let headerLine = null;
      
      for (const line of tableLines) {
        if (line.trim()) {
          // Split by multiple spaces
          const cells = line.split(/\s{2,}/)
            .map(cell => cell.trim())
            .filter(cell => cell !== '');
          
          console.log('Processed line into cells:', cells);
          
          if (cells.length > 1) {
            if (!headerLine) {
              headerLine = cells;
            } else {
              dataLines.push(cells);
            }
          }
        }
      }
      
      console.log('Header:', headerLine);
      console.log('Data rows:', dataLines);
      
      if (headerLine && dataLines.length > 0) {
        console.log('✅ Found valid table! Converting to markdown...');
        
        // Build markdown table
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
        
        // Replace the original table section with markdown
        const originalTableSection = lines.slice(startIdx, endIdx + 1).join('\n');
        console.log('Replacing table section:', originalTableSection.substring(0, 50) + '...');
        
        return content.replace(originalTableSection, markdownTable);
      }
    }
  }
  
  console.log('No valid ASCII tables found');
  return content;
}

console.log("=== TESTING NEW APPROACH ===");
const result = convertASCIIDashTableToMarkdown(testContent);
console.log("\n=== RESULT ===");
console.log(result);

const hasMarkdownTable = result.includes('|') && result.includes('---');
console.log("\nContains markdown table:", hasMarkdownTable);