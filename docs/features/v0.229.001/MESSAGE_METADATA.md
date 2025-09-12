# Message Metadata Feature

**Version Implemented:** 0.229.001

## Overview
The Message Metadata feature introduces comprehensive tracking and display of detailed information about each message in conversations, including timestamps, token usage, model information, processing time, and other relevant metadata that enhances transparency and debugging capabilities.

## Purpose
Message Metadata enables users and administrators to:
- Track token usage and costs for each message exchange
- Monitor processing times and performance metrics
- Identify which AI models were used for specific responses
- Debug conversation issues with detailed technical information
- Analyze conversation patterns and efficiency
- Provide transparency in AI interactions

## Technical Specifications

### Architecture Overview
- **Real-time Collection**: Metadata captured during message processing
- **Structured Storage**: Metadata stored alongside message content in Cosmos DB
- **UI Integration**: Expandable metadata display in chat interface
- **Performance Tracking**: Processing time and token usage monitoring

### Database Schema
```json
{
  "message_id": "msg-uuid-12345",
  "conversation_id": "conv-uuid-67890",
  "user_id": "user-uuid-abcde",
  "content": "What is machine learning?",
  "role": "user",
  "timestamp": "2025-09-12T10:30:00Z",
  "metadata": {
    "processing_time_ms": 1250,
    "token_usage": {
      "prompt_tokens": 45,
      "completion_tokens": 187,
      "total_tokens": 232
    },
    "model_info": {
      "deployment_name": "gpt-4o",
      "model_version": "2024-11-30",
      "temperature": 0.7,
      "max_tokens": 4000
    },
    "search_metadata": {
      "documents_searched": 12,
      "relevant_chunks": 3,
      "search_time_ms": 340,
      "search_query": "machine learning definition"
    },
    "safety_check": {
      "content_safety_enabled": true,
      "safety_check_time_ms": 156,
      "safety_result": "safe"
    },
    "response_metadata": {
      "finish_reason": "stop",
      "created_at": "2025-09-12T10:30:01.250Z",
      "response_id": "resp-uuid-fghij"
    },
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)...",
    "ip_address": "192.168.1.100", // Hashed for privacy
    "session_id": "session-uuid-klmno"
  }
}
```

### Metadata Collection System
```javascript
class MessageMetadataCollector {
    constructor() {
        this.startTime = null;
        this.endTime = null;
        this.metadata = {};
    }
    
    startCollection(messageData) {
        this.startTime = performance.now();
        this.metadata = {
            message_id: messageData.message_id,
            user_id: messageData.user_id,
            conversation_id: messageData.conversation_id,
            timestamp: new Date().toISOString(),
            user_agent: navigator.userAgent,
            session_id: this.getSessionId(),
            client_metadata: {
                viewport_size: {
                    width: window.innerWidth,
                    height: window.innerHeight
                },
                browser_info: this.getBrowserInfo(),
                timezone: Intl.DateTimeFormat().resolvedOptions().timeZone
            }
        };
    }
    
    addTokenUsage(tokenData) {
        this.metadata.token_usage = {
            prompt_tokens: tokenData.prompt_tokens,
            completion_tokens: tokenData.completion_tokens,
            total_tokens: tokenData.total_tokens,
            estimated_cost: this.calculateCost(tokenData)
        };
    }
    
    addModelInfo(modelData) {
        this.metadata.model_info = {
            deployment_name: modelData.deployment,
            model_version: modelData.version,
            temperature: modelData.temperature,
            max_tokens: modelData.max_tokens,
            provider: modelData.provider || 'azure_openai'
        };
    }
    
    addSearchMetadata(searchData) {
        this.metadata.search_metadata = {
            documents_searched: searchData.total_documents,
            relevant_chunks: searchData.returned_chunks,
            search_time_ms: searchData.processing_time,
            search_query: searchData.query,
            search_filters: searchData.filters
        };
    }
    
    finishCollection(responseData) {
        this.endTime = performance.now();
        this.metadata.processing_time_ms = Math.round(this.endTime - this.startTime);
        this.metadata.response_metadata = {
            finish_reason: responseData.finish_reason,
            created_at: responseData.created_at,
            response_id: responseData.id
        };
        
        return this.metadata;
    }
    
    calculateCost(tokenData) {
        // Token cost calculation based on model pricing
        const costPerThousand = {
            'gpt-4o': { input: 0.005, output: 0.015 },
            'gpt-35-turbo': { input: 0.0015, output: 0.002 }
        };
        
        const modelCost = costPerThousand[this.metadata.model_info?.deployment_name] || 
                         costPerThousand['gpt-4o'];
        
        const inputCost = (tokenData.prompt_tokens / 1000) * modelCost.input;
        const outputCost = (tokenData.completion_tokens / 1000) * modelCost.output;
        
        return {
            input_cost: inputCost,
            output_cost: outputCost,
            total_cost: inputCost + outputCost,
            currency: 'USD'
        };
    }
}
```

## Configuration Options

### Admin Settings
```html
<div class="message-metadata-settings">
    <h5>Message Metadata Configuration</h5>
    
    <div class="form-group">
        <div class="form-check">
            <input type="checkbox" id="enable-message-metadata" class="form-check-input" checked>
            <label class="form-check-label">Enable Message Metadata Collection</label>
            <small class="form-text text-muted">Collect detailed information about each message</small>
        </div>
    </div>
    
    <div class="form-group">
        <div class="form-check">
            <input type="checkbox" id="show-metadata-to-users" class="form-check-input" checked>
            <label class="form-check-label">Show Metadata to Users</label>
            <small class="form-text text-muted">Allow users to view message metadata in chat interface</small>
        </div>
    </div>
    
    <div class="form-group">
        <div class="form-check">
            <input type="checkbox" id="collect-token-usage" class="form-check-input" checked>
            <label class="form-check-label">Collect Token Usage Data</label>
        </div>
    </div>
    
    <div class="form-group">
        <div class="form-check">
            <input type="checkbox" id="collect-timing-data" class="form-check-input" checked>
            <label class="form-check-label">Collect Processing Time Data</label>
        </div>
    </div>
    
    <div class="form-group">
        <div class="form-check">
            <input type="checkbox" id="collect-search-metadata" class="form-check-input" checked>
            <label class="form-check-label">Collect Document Search Metadata</label>
        </div>
    </div>
    
    <div class="form-group">
        <label>Privacy Settings</label>
        <div class="form-check">
            <input type="checkbox" id="hash-ip-addresses" class="form-check-input" checked>
            <label class="form-check-label">Hash IP Addresses for Privacy</label>
        </div>
        <div class="form-check">
            <input type="checkbox" id="anonymize-user-agents" class="form-check-input">
            <label class="form-check-label">Anonymize User Agent Strings</label>
        </div>
    </div>
    
    <div class="form-group">
        <label>Data Retention</label>
        <select class="form-control" id="metadata-retention-days">
            <option value="30">30 Days</option>
            <option value="90" selected>90 Days</option>
            <option value="180">180 Days</option>
            <option value="365">1 Year</option>
            <option value="-1">Indefinite</option>
        </select>
        <small class="form-text text-muted">How long to retain detailed metadata</small>
    </div>
</div>
```

## Usage Instructions

### For End Users

#### Viewing Message Metadata
1. **Access Metadata**: Click the info icon (ⓘ) next to any message
2. **Expandable Display**: Click "Show Details" to expand full metadata
3. **Copy Information**: Use copy buttons to copy specific metadata values
4. **Performance Insights**: View response times and token usage

#### Metadata Display Interface
```html
<div class="message-metadata-display">
    <div class="metadata-summary">
        <span class="metadata-item">
            <i class="fas fa-clock"></i>
            <span class="metadata-value">1.25s</span>
        </span>
        <span class="metadata-item">
            <i class="fas fa-coins"></i>
            <span class="metadata-value">232 tokens</span>
        </span>
        <span class="metadata-item">
            <i class="fas fa-brain"></i>
            <span class="metadata-value">GPT-4o</span>
        </span>
    </div>
    
    <div class="metadata-details" style="display: none;">
        <div class="metadata-section">
            <h6>Token Usage</h6>
            <table class="table table-sm">
                <tr>
                    <td>Prompt Tokens:</td>
                    <td>45</td>
                </tr>
                <tr>
                    <td>Completion Tokens:</td>
                    <td>187</td>
                </tr>
                <tr>
                    <td>Total Tokens:</td>
                    <td>232</td>
                </tr>
                <tr>
                    <td>Estimated Cost:</td>
                    <td>$0.003</td>
                </tr>
            </table>
        </div>
        
        <div class="metadata-section">
            <h6>Model Information</h6>
            <table class="table table-sm">
                <tr>
                    <td>Deployment:</td>
                    <td>gpt-4o</td>
                </tr>
                <tr>
                    <td>Version:</td>
                    <td>2024-11-30</td>
                </tr>
                <tr>
                    <td>Temperature:</td>
                    <td>0.7</td>
                </tr>
            </table>
        </div>
        
        <div class="metadata-section">
            <h6>Performance</h6>
            <table class="table table-sm">
                <tr>
                    <td>Processing Time:</td>
                    <td>1,250ms</td>
                </tr>
                <tr>
                    <td>Search Time:</td>
                    <td>340ms</td>
                </tr>
                <tr>
                    <td>Safety Check:</td>
                    <td>156ms</td>
                </tr>
            </table>
        </div>
    </div>
    
    <button class="btn btn-sm btn-outline-secondary toggle-details">
        Show Details
    </button>
</div>
```

### For Administrators

#### Metadata Analytics Dashboard
```javascript
class MetadataAnalytics {
    async generateUsageReport(dateRange) {
        const report = {
            totalMessages: 0,
            totalTokens: 0,
            totalCost: 0,
            averageResponseTime: 0,
            modelUsage: {},
            performanceMetrics: {
                fastest_response: null,
                slowest_response: null,
                average_search_time: 0
            }
        };
        
        const messages = await this.fetchMessagesInRange(dateRange);
        
        messages.forEach(msg => {
            if (msg.metadata) {
                report.totalMessages++;
                report.totalTokens += msg.metadata.token_usage?.total_tokens || 0;
                report.totalCost += msg.metadata.token_usage?.estimated_cost?.total_cost || 0;
                
                // Model usage tracking
                const model = msg.metadata.model_info?.deployment_name;
                if (model) {
                    report.modelUsage[model] = (report.modelUsage[model] || 0) + 1;
                }
                
                // Performance tracking
                const responseTime = msg.metadata.processing_time_ms;
                if (responseTime) {
                    if (!report.performanceMetrics.fastest_response || 
                        responseTime < report.performanceMetrics.fastest_response) {
                        report.performanceMetrics.fastest_response = responseTime;
                    }
                    if (!report.performanceMetrics.slowest_response || 
                        responseTime > report.performanceMetrics.slowest_response) {
                        report.performanceMetrics.slowest_response = responseTime;
                    }
                }
            }
        });
        
        report.averageResponseTime = this.calculateAverageResponseTime(messages);
        
        return report;
    }
}
```

#### Metadata Export Functionality
```python
import csv
import json
from datetime import datetime, timedelta

class MetadataExporter:
    def export_metadata_csv(self, date_range, include_sensitive=False):
        """Export message metadata to CSV format"""
        messages = self.get_messages_with_metadata(date_range)
        
        csv_data = []
        for message in messages:
            metadata = message.get('metadata', {})
            
            row = {
                'message_id': message['message_id'],
                'timestamp': message['timestamp'],
                'processing_time_ms': metadata.get('processing_time_ms'),
                'total_tokens': metadata.get('token_usage', {}).get('total_tokens'),
                'estimated_cost': metadata.get('token_usage', {}).get('estimated_cost', {}).get('total_cost'),
                'model_deployment': metadata.get('model_info', {}).get('deployment_name'),
                'model_version': metadata.get('model_info', {}).get('model_version'),
                'documents_searched': metadata.get('search_metadata', {}).get('documents_searched'),
                'search_time_ms': metadata.get('search_metadata', {}).get('search_time_ms')
            }
            
            # Include sensitive data only if requested and authorized
            if include_sensitive:
                row['user_id'] = message['user_id']
                row['conversation_id'] = message['conversation_id']
                row['ip_address'] = metadata.get('ip_address')
            
            csv_data.append(row)
        
        return csv_data
```

## Integration Points

### Chat Interface Integration
```javascript
// Add metadata display to each message
function renderMessageWithMetadata(message) {
    const messageElement = document.createElement('div');
    messageElement.className = 'chat-message';
    
    // Message content
    const contentElement = document.createElement('div');
    contentElement.className = 'message-content';
    contentElement.innerHTML = message.content;
    
    // Metadata toggle
    const metadataToggle = document.createElement('button');
    metadataToggle.className = 'btn btn-sm btn-outline-secondary metadata-toggle';
    metadataToggle.innerHTML = '<i class="fas fa-info-circle"></i>';
    metadataToggle.onclick = () => toggleMetadata(message.message_id);
    
    // Metadata display
    const metadataDisplay = document.createElement('div');
    metadataDisplay.className = 'message-metadata';
    metadataDisplay.id = `metadata-${message.message_id}`;
    metadataDisplay.style.display = 'none';
    metadataDisplay.innerHTML = renderMetadataDetails(message.metadata);
    
    messageElement.appendChild(contentElement);
    messageElement.appendChild(metadataToggle);
    messageElement.appendChild(metadataDisplay);
    
    return messageElement;
}
```

### Performance Monitoring Integration
```javascript
class PerformanceMonitor {
    constructor() {
        this.thresholds = {
            response_time_warning: 5000, // 5 seconds
            response_time_critical: 10000, // 10 seconds
            token_usage_warning: 4000,
            token_usage_critical: 8000
        };
    }
    
    analyzeMessagePerformance(metadata) {
        const alerts = [];
        
        // Check response time
        if (metadata.processing_time_ms > this.thresholds.response_time_critical) {
            alerts.push({
                type: 'critical',
                message: `Response time (${metadata.processing_time_ms}ms) exceeded critical threshold`
            });
        } else if (metadata.processing_time_ms > this.thresholds.response_time_warning) {
            alerts.push({
                type: 'warning',
                message: `Response time (${metadata.processing_time_ms}ms) exceeded warning threshold`
            });
        }
        
        // Check token usage
        const totalTokens = metadata.token_usage?.total_tokens;
        if (totalTokens > this.thresholds.token_usage_critical) {
            alerts.push({
                type: 'critical',
                message: `Token usage (${totalTokens}) exceeded critical threshold`
            });
        } else if (totalTokens > this.thresholds.token_usage_warning) {
            alerts.push({
                type: 'warning',
                message: `Token usage (${totalTokens}) exceeded warning threshold`
            });
        }
        
        return alerts;
    }
}
```

## Privacy and Security Considerations

### Data Privacy
```python
import hashlib
import hmac

class MetadataPrivacy:
    def __init__(self, secret_key):
        self.secret_key = secret_key
    
    def hash_ip_address(self, ip_address):
        """Hash IP addresses for privacy while maintaining uniqueness"""
        return hmac.new(
            self.secret_key.encode(),
            ip_address.encode(),
            hashlib.sha256
        ).hexdigest()[:16]
    
    def anonymize_user_agent(self, user_agent):
        """Remove potentially identifying information from user agent"""
        # Remove version numbers and specific browser versions
        import re
        anonymized = re.sub(r'\d+\.\d+\.\d+\.\d+', 'x.x.x.x', user_agent)
        anonymized = re.sub(r'Chrome/\d+\.\d+\.\d+\.\d+', 'Chrome/xxx', anonymized)
        return anonymized
    
    def sanitize_metadata_for_export(self, metadata, user_role):
        """Remove sensitive information based on user role"""
        sanitized = metadata.copy()
        
        if user_role != 'Admin':
            # Remove sensitive fields for non-admin users
            sanitized.pop('ip_address', None)
            sanitized.pop('session_id', None)
            sanitized.pop('user_agent', None)
        
        return sanitized
```

### Data Retention
```python
from datetime import datetime, timedelta

class MetadataRetention:
    def cleanup_old_metadata(self, retention_days):
        """Remove metadata older than specified retention period"""
        cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
        
        # Query messages older than cutoff date
        old_messages = self.cosmos_client.query_items(
            container=self.conversations_container,
            query="SELECT * FROM c WHERE c.timestamp < @cutoff_date",
            parameters=[{"name": "@cutoff_date", "value": cutoff_date.isoformat()}]
        )
        
        for message in old_messages:
            # Remove detailed metadata but keep basic info
            if 'metadata' in message:
                # Keep only essential metadata
                essential_metadata = {
                    'processing_time_ms': message['metadata'].get('processing_time_ms'),
                    'total_tokens': message['metadata'].get('token_usage', {}).get('total_tokens'),
                    'model_deployment': message['metadata'].get('model_info', {}).get('deployment_name')
                }
                message['metadata'] = essential_metadata
                
                # Update the document
                self.cosmos_client.upsert_item(
                    container=self.conversations_container,
                    body=message
                )
```

## Testing and Validation

### Functional Testing
- Verify metadata collection for all message types (user, assistant, system)
- Test metadata display toggle functionality in chat interface
- Validate token usage calculations for different models
- Confirm processing time measurements are accurate

### Performance Testing
- Measure impact of metadata collection on message processing time
- Test metadata storage and retrieval performance with large datasets
- Validate memory usage during extended conversations with metadata

### Privacy Testing
- Verify IP address hashing works correctly
- Test data retention cleanup functionality
- Confirm sensitive data removal for non-admin users
- Validate export functionality respects privacy settings

## Known Limitations
- Metadata collection adds slight overhead to message processing
- Some metadata fields may not be available for all message types
- Token usage calculations are estimates based on known model pricing
- Processing time includes network latency and may vary significantly

## Future Enhancements
- Real-time performance alerting for slow responses
- Advanced analytics dashboard with trend analysis
- Integration with external monitoring systems
- Custom metadata fields for organization-specific tracking
- Automated performance optimization recommendations based on metadata analysis