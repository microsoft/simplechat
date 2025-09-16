#!/usr/bin/env python3
"""
Test to verify table markdown processing and identify AI response format issues.
Version: 0.229.003
Implemented in: 0.229.003

This test investigates how different markdown formats are processed and
identifies why AI-generated tables may not be rendering correctly.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_markdown_table_processing():
    """Test various table markdown formats to identify parsing issues."""
    print("🔍 Testing Markdown Table Processing...")
    
    # Test cases representing different AI response formats
    test_cases = [
        {
            "name": "Raw Table Markdown",
            "content": """| License Type | Description | Price |
|--------------|-------------|-------|
| Standard     | Basic features | $10  |
| Premium      | Advanced features | $25 |""",
            "expected": "Should render as HTML table"
        },
        {
            "name": "Table in Code Block",
            "content": """```
| License Type | Description | Price |
|--------------|-------------|-------|
| Standard     | Basic features | $10  |
| Premium      | Advanced features | $25 |
```""",
            "expected": "Should render as code block (NOT table)"
        },
        {
            "name": "Mixed Content with Table",
            "content": """Here are the license options:

| License Type | Description | Price |
|--------------|-------------|-------|
| Standard     | Basic features | $10  |
| Premium      | Advanced features | $25 |

Choose the one that fits your needs.""",
            "expected": "Should render text + HTML table + text"
        },
        {
            "name": "AI Response Simulation - Wrapped in Code",
            "content": """Here's the information you requested:

```
| License Type | Description | Price |
|--------------|-------------|-------|
| Standard     | Basic features | $10  |
| Premium      | Advanced features | $25 |
```

This format prevents table rendering.""",
            "expected": "Text + code block (table won't render)"
        },
        {
            "name": "AI Response Simulation - Proper Format",
            "content": """Here's the information you requested:

| License Type | Description | Price |
|--------------|-------------|-------|
| Standard     | Basic features | $10  |
| Premium      | Advanced features | $25 |

This format allows table rendering.""",
            "expected": "Text + HTML table + text"
        }
    ]
    
    # Create test HTML file to verify processing
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Table Processing Analysis</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        /* Copy table styles from chats.css */
        .message-text table {
            width: 100%;
            border-collapse: collapse;
            margin: 1rem 0;
            border: 1px solid #dee2e6;
            border-radius: 0.375rem;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }
        .message-text thead {
            background: linear-gradient(135deg, #007bff 0%, #0056b3 100%);
            color: white;
        }
        .message-text th, .message-text td {
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid #dee2e6;
            vertical-align: top;
        }
        .message-text th {
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.875rem;
            letter-spacing: 0.5px;
            text-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
        }
        .message-text tbody tr:nth-child(even) {
            background-color: #f8f9fa;
        }
        .message-text tbody tr:hover {
            background-color: #e9ecef;
            transition: background-color 0.2s ease;
        }
        .test-case {
            border: 1px solid #ddd;
            margin: 20px 0;
            padding: 15px;
            border-radius: 5px;
        }
        .input-content {
            background: #f8f9fa;
            padding: 10px;
            border-radius: 3px;
            font-family: monospace;
            white-space: pre-wrap;
            margin: 10px 0;
        }
        .result-good { border-left: 5px solid #28a745; }
        .result-bad { border-left: 5px solid #dc3545; }
    </style>
</head>
<body>
    <div class="container mt-4">
        <h1>Table Processing Analysis</h1>
        <p class="lead">Analyzing how different markdown formats are processed to identify AI response issues.</p>
"""
    
    for i, test_case in enumerate(test_cases):
        html_content += f"""
        <div class="test-case" id="test-{i}">
            <h3>{test_case['name']}</h3>
            <p><strong>Expected:</strong> {test_case['expected']}</p>
            
            <h5>Input:</h5>
            <div class="input-content">{test_case['content']}</div>
            
            <h5>Rendered Output:</h5>
            <div class="message-text" id="output-{i}"></div>
        </div>
"""
    
    html_content += """
    </div>

    <script src="https://cdn.jsdelivr.net/npm/marked@15.0.7/marked.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/dompurify@3.1.7/dist/purify.min.js"></script>
    <script>
        // Configure marked for GFM (should support tables by default)
        marked.setOptions({
            gfm: true,
            breaks: true,
            tables: true
        });

        const testCases = """
    
    # Add test cases as JavaScript array
    js_test_cases = str(test_cases).replace("'", '"').replace('"""', '`')
    html_content += js_test_cases
    
    html_content += """;

        // Process each test case
        testCases.forEach((testCase, index) => {
            const outputDiv = document.getElementById(`output-${index}`);
            const testDiv = document.getElementById(`test-${index}`);
            
            try {
                const htmlContent = DOMPurify.sanitize(marked.parse(testCase.content));
                outputDiv.innerHTML = htmlContent;
                
                // Check if table was rendered
                const hasTable = outputDiv.querySelector('table');
                const hasCodeBlock = outputDiv.querySelector('pre code');
                
                if (hasTable && !hasCodeBlock) {
                    testDiv.classList.add('result-good');
                    console.log(`✅ ${testCase.name}: Table rendered correctly`);
                } else if (hasCodeBlock && testCase.name.includes('Code Block')) {
                    testDiv.classList.add('result-good');
                    console.log(`✅ ${testCase.name}: Code block rendered correctly (expected)`);
                } else if (hasCodeBlock && testCase.content.includes('```')) {
                    testDiv.classList.add('result-bad');
                    console.log(`❌ ${testCase.name}: Table in code block (prevents table rendering)`);
                } else {
                    testDiv.classList.add('result-bad');
                    console.log(`❌ ${testCase.name}: Unexpected result`);
                }
                
                console.log(`${testCase.name}:`, {
                    hasTable: !!hasTable,
                    hasCodeBlock: !!hasCodeBlock,
                    html: htmlContent.substring(0, 200) + '...'
                });
                
            } catch (error) {
                console.error(`Error processing ${testCase.name}:`, error);
                outputDiv.innerHTML = '<div class="alert alert-danger">Error processing content</div>';
                testDiv.classList.add('result-bad');
            }
        });
    </script>
</body>
</html>"""
    
    # Write the test file
    test_file = os.path.join(os.path.dirname(__file__), "table_processing_analysis.html")
    with open(test_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"✅ Created test file: {test_file}")
    print("📋 Test cases created:")
    for i, case in enumerate(test_cases):
        print(f"  {i+1}. {case['name']}")
    
    print("\n🔧 To view results:")
    print("1. Open the HTML file in a browser")
    print("2. Check console for detailed analysis")
    print("3. Green border = working correctly")
    print("4. Red border = issue identified")
    
    return True

def analyze_potential_solutions():
    """Analyze potential solutions for the table rendering issue."""
    print("\n🔧 Analyzing Potential Solutions...")
    
    solutions = [
        {
            "solution": "Pre-process AI responses to remove unnecessary code blocks",
            "description": "Detect and unwrap tables that are mistakenly wrapped in code blocks",
            "pros": ["Fixes root cause", "Maintains all other formatting"],
            "cons": ["Complex pattern matching", "Risk of false positives"],
            "implementation": "Add preprocessing step before marked.parse()"
        },
        {
            "solution": "Agent instructions to avoid code blocks for tables",
            "description": "Update agent prompts to explicitly use raw markdown tables",
            "pros": ["Simple", "No code changes needed"],
            "cons": ["Doesn't fix existing behavior", "Relies on AI compliance"],
            "implementation": "Update system prompts"
        },
        {
            "solution": "Hybrid approach: preprocessing + instructions",
            "description": "Combine both approaches for maximum effectiveness",
            "pros": ["Most robust", "Handles all cases"],
            "cons": ["More complex implementation"],
            "implementation": "Update prompts AND add preprocessing"
        }
    ]
    
    print("📋 Solution Analysis:")
    for i, sol in enumerate(solutions, 1):
        print(f"\n{i}. {sol['solution']}")
        print(f"   Description: {sol['description']}")
        print(f"   Implementation: {sol['implementation']}")
        print(f"   Pros: {', '.join(sol['pros'])}")
        print(f"   Cons: {', '.join(sol['cons'])}")
    
    print("\n💡 Recommended approach: Solution 3 (Hybrid)")
    print("   - Start with preprocessing to fix immediate issue")
    print("   - Update agent prompts for future responses")
    print("   - Ensures both existing and new content works correctly")
    
    return True

if __name__ == "__main__":
    print("🧪 Table Markdown Processing Analysis")
    print("=" * 50)
    
    try:
        success1 = test_markdown_table_processing()
        success2 = analyze_potential_solutions()
        
        overall_success = success1 and success2
        
        print("\n" + "=" * 50)
        if overall_success:
            print("✅ Analysis completed successfully!")
            print("📄 Review the generated HTML file for visual confirmation")
            print("🔧 Implement the recommended hybrid solution")
        else:
            print("❌ Analysis failed")
            
        sys.exit(0 if overall_success else 1)
        
    except Exception as e:
        print(f"❌ Analysis failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)