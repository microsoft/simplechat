#!/bin/bash

# Azure CLI Script to Create Cosmos DB Database and Containers
# This script creates the SimpleChat database and all required containers with proper existence checking

# For Cloud Shell, open the script editor and copy this in, setting your variables below.
# Save it to the local ephemeral storage (Files), and refresh the Files pane.
# Run "chmod +x <your-script-name>" to make it executable.
# Finally, run the script with "./<your-script-name>"

# Set variables
RESOURCE_GROUP="your-resource-group"
ACCOUNT_NAME="your-cosmos-account-name"
DATABASE_NAME="SimpleChat"

# Function to check if database exists
check_database_exists() {
    az cosmosdb sql database show \
        --resource-group "$RESOURCE_GROUP" \
        --account-name "$ACCOUNT_NAME" \
        --name "$DATABASE_NAME" \
        --output none 2>/dev/null
    return $?
}

# Function to check if container exists
check_container_exists() {
    local container_name="$1"
    az cosmosdb sql container show \
        --resource-group "$RESOURCE_GROUP" \
        --account-name "$ACCOUNT_NAME" \
        --database-name "$DATABASE_NAME" \
        --name "$container_name" \
        --output none 2>/dev/null
    return $?
}

# Function to create container if it doesn't exist
create_container_if_not_exists() {
    local container_name="$1"
    local partition_key="$2"
    
    if check_container_exists "$container_name"; then
        echo "Container '$container_name' already exists"
    else
        echo "Creating container '$container_name'..."
        az cosmosdb sql container create \
            --resource-group "$RESOURCE_GROUP" \
            --account-name "$ACCOUNT_NAME" \
            --database-name "$DATABASE_NAME" \
            --name "$container_name" \
            --partition-key-path "$partition_key" \
            --throughput 400
        
        if [ $? -eq 0 ]; then
            echo "Container '$container_name' created successfully"
        else
            echo "Failed to create container '$container_name'"
            exit 1
        fi
    fi
}

# Create database if it doesn't exist
if check_database_exists; then
    echo "Database '$DATABASE_NAME' already exists"
else
    echo "Creating database '$DATABASE_NAME'..."
    az cosmosdb sql database create \
        --resource-group "$RESOURCE_GROUP" \
        --account-name "$ACCOUNT_NAME" \
        --name "$DATABASE_NAME" \
        --throughput 1000
    
    if [ $? -eq 0 ]; then
        echo "Database '$DATABASE_NAME' created successfully"
    else
        echo "Failed to create database '$DATABASE_NAME'"
        exit 1
    fi
fi

# Create all containers
echo "Creating containers..."

create_container_if_not_exists "conversations" "/id"
create_container_if_not_exists "messages" "/conversation_id"
create_container_if_not_exists "settings" "/id"
create_container_if_not_exists "groups" "/id"
create_container_if_not_exists "public_workspaces" "/id"
create_container_if_not_exists "documents" "/id"
create_container_if_not_exists "group_documents" "/id"
create_container_if_not_exists "public_documents" "/id"
create_container_if_not_exists "user_settings" "/id"
create_container_if_not_exists "safety" "/id"
create_container_if_not_exists "feedback" "/id"
create_container_if_not_exists "archived_conversations" "/id"
create_container_if_not_exists "archived_messages" "/conversation_id"
create_container_if_not_exists "prompts" "/id"
create_container_if_not_exists "group_prompts" "/id"
create_container_if_not_exists "public_prompts" "/id"
create_container_if_not_exists "file_processing" "/document_id"
create_container_if_not_exists "personal_agents" "/user_id"
create_container_if_not_exists "personal_actions" "/user_id"
create_container_if_not_exists "group_messages" "/conversation_id"
create_container_if_not_exists "group_conversations" "/id"
create_container_if_not_exists "group_agents" "/group_id"
create_container_if_not_exists "group_actions" "/group_id"
create_container_if_not_exists "global_agents" "/id"
create_container_if_not_exists "global_actions" "/id"
create_container_if_not_exists "agent_facts" "/scope_id"

echo "All containers created or verified successfully"