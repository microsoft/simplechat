# Azure PowerShell Script to Create Cosmos DB Database and Containers
# This script creates the SimpleChat database and all required containers with proper existence checking

# Set variables
$ResourceGroupName = "your-resource-group"
$AccountName = "your-cosmos-account-name"
$DatabaseName = "SimpleChat"
$AutoscaleDatabaseMaxThroughput = 1000

# Function to check if database exists
function Test-DatabaseExists {
    param($ResourceGroup, $Account, $Database)
    
    try {
        $null = Get-AzCosmosDBSqlDatabase -ResourceGroupName $ResourceGroup -AccountName $Account -Name $Database -ErrorAction Stop
        return $true
    }
    catch {
        return $false
    }
}

# Function to check if container exists
function Test-ContainerExists {
    param($ResourceGroup, $Account, $Database, $Container)
    
    try {
        $null = Get-AzCosmosDBSqlContainer -ResourceGroupName $ResourceGroup -AccountName $Account -DatabaseName $Database -Name $Container -ErrorAction Stop
        return $true
    }
    catch {
        return $false
    }
}

# Function to create container if it doesn't exist
function New-ContainerIfNotExists {
    param($ResourceGroup, $Account, $Database, $ContainerName, $PartitionKeyPath, $PartitionKeyType, $Throughput = 400)
    
    if (Test-ContainerExists -ResourceGroup $ResourceGroup -Account $Account -Database $Database -Container $ContainerName) {
        Write-Host "Container '$ContainerName' already exists" -ForegroundColor Yellow
    }
    else {
        Write-Host "Creating container '$ContainerName' with dedicated throughput ($Throughput RU/s)..." -ForegroundColor Green
        try {
            New-AzCosmosDBSqlContainer -ResourceGroupName $ResourceGroup -AccountName $Account -DatabaseName $Database -Name $ContainerName -PartitionKeyPath $PartitionKeyPath -PartitionKeyKind $PartitionKeyType -Throughput $Throughput -ErrorAction Stop
            Write-Host "Container '$ContainerName' created successfully" -ForegroundColor Green
        }
        catch {
            Write-Error "Failed to create container '$ContainerName': $($_.Exception.Message)"
            throw
        }
    }
}

# Create database if it doesn't exist
if (Test-DatabaseExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName) {
    Write-Host "Database '$DatabaseName' already exists`n" -ForegroundColor Yellow
}
else {
    Write-Host "Creating database '$DatabaseName'..." -ForegroundColor Green
    try {
        New-AzCosmosDBSqlDatabase -ResourceGroupName $ResourceGroupName -AccountName $AccountName -Name $DatabaseName -ErrorAction Stop
        Write-Host "Database '$DatabaseName' created successfully" -ForegroundColor Green
    }
    catch {
        Write-Error "Failed to create database '$DatabaseName': $($_.Exception.Message)"
        exit 1
    }
}

# Create all containers
Write-Host "Creating containers..." -ForegroundColor Cyan

try {
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "conversations" -PartitionKeyPath "/id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "messages" -PartitionKeyPath "/conversation_id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "settings" -PartitionKeyPath "/id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "groups" -PartitionKeyPath "/id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "public_workspaces" -PartitionKeyPath "/id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "documents" -PartitionKeyPath "/id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "group_documents" -PartitionKeyPath "/id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "public_documents" -PartitionKeyPath "/id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "user_settings" -PartitionKeyPath "/id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "safety" -PartitionKeyPath "/id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "feedback" -PartitionKeyPath "/id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "archived_conversations" -PartitionKeyPath "/id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "archived_messages" -PartitionKeyPath "/conversation_id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "prompts" -PartitionKeyPath "/id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "group_prompts" -PartitionKeyPath "/id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "public_prompts" -PartitionKeyPath "/id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "file_processing" -PartitionKeyPath "/document_id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "personal_agents" -PartitionKeyPath "/user_id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "personal_actions" -PartitionKeyPath "/user_id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "group_messages" -PartitionKeyPath "/conversation_id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "group_conversations" -PartitionKeyPath "/id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "group_agents" -PartitionKeyPath "/group_id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "group_actions" -PartitionKeyPath "/group_id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "global_agents" -PartitionKeyPath "/id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "global_actions" -PartitionKeyPath "/id" -PartitionKeyType "Hash"
    New-ContainerIfNotExists -ResourceGroup $ResourceGroupName -Account $AccountName -Database $DatabaseName -ContainerName "agent_facts" -PartitionKeyPath "/scope_id" -PartitionKeyType "Hash"

    Write-Host "All containers created or verified successfully" -ForegroundColor Green
}
catch {
    Write-Error "Script execution failed: $($_.Exception.Message)"
    exit 1
}