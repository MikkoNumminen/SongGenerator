// Everything this project puts in the cloud, which is one static site.
//
// Subscription scope so a single command creates the resource group and the
// site together, and so `what-if` works against a subscription that has
// neither yet. Deploy with:
//
//   az deployment sub create --location westeurope \
//       --template-file infra/main.bicep --parameters infra/main.bicepparam
//
// Nothing else about this system is in the cloud, and that is a decision
// rather than an omission: the pipeline needs a GPU and the job history has to
// sit beside it. docs/AZURE.md records what was considered and why.

targetScope = 'subscription'

@description('Name of the static site, and the suffix of its resource group.')
@minLength(2)
@maxLength(40)
param name string = 'songgen-web'

@description('''
Where the resources are managed. Static Web Apps are offered in a handful of
regions and serve their content from Microsoft's edge regardless, so this
decides where the resource lives rather than where anyone downloads from.
''')
@allowed([
  'westeurope'
  'northeurope'
  'centralus'
  'eastus2'
  'westus2'
  'eastasia'
])
param location string = 'westeurope'

resource group 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${name}'
  location: location
}

module site 'site.bicep' = {
  name: 'site'
  scope: group
  params: {
    name: name
    location: location
  }
}

@description('Where the site answers once something has been deployed to it.')
output defaultHostname string = site.outputs.defaultHostname

@description('The resource group and site name the pipeline needs to fetch a deployment token.')
output resourceGroupName string = group.name
output siteName string = site.outputs.siteName
