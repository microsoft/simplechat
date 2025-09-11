// Test OpenAPI file status display logic
function getFileStatus(hasUploadedFile, hasDataset) {
  let fileName;
  
  if (hasUploadedFile) {
    fileName = 'new-file.yaml';
  } else if (hasDataset) {
    fileName = 'No changes (using existing specification)';
  } else {
    fileName = '-';
  }
  
  return fileName;
}

console.log('=== OPENAPI FILE STATUS TEST ===');

const scenarios = [
  { hasUploaded: true, hasDataset: false, description: 'New file uploaded' },
  { hasUploaded: false, hasDataset: true, description: 'Editing existing (no new file)' },
  { hasUploaded: false, hasDataset: false, description: 'No file at all' },
  { hasUploaded: true, hasDataset: true, description: 'New file uploaded over existing' }
];

scenarios.forEach((scenario, i) => {
  const result = getFileStatus(scenario.hasUploaded, scenario.hasDataset);
  console.log(`Scenario ${i+1}: ${scenario.description} -> "${result}"`);
});

console.log('=== TEST COMPLETE ===');
