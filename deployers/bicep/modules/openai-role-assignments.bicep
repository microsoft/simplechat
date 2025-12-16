param openAiResourceName string
param assignmentGuid string
param roleDefinitionId string
param principalId string
param principalType string = 'ServicePrincipal'


resource openAi 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: openAiResourceName
}

resource appRegSpToOpenAIAccess_User 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: assignmentGuid
  scope: openAi
  properties: {
    roleDefinitionId: roleDefinitionId
    principalId: principalId
    principalType: principalType
  }
}
