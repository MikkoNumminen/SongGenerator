// The static site itself. Deployed by main.bicep, which owns the resource
// group; kept separate so the group and the thing in it are not one blob.
//
// Free plan, which costs nothing: the 100 GB monthly bandwidth is a
// subscription-wide allowance against a bundle of a few hundred kilobytes, and
// the 250 MB per-environment limit is far above a build this size.

targetScope = 'resourceGroup'

@description('Name of the static site. Must be unique within the subscription.')
@minLength(2)
@maxLength(40)
param name string = 'songgen-web'

@description('''
Where the site's metadata lives. Static Web Apps are only offered in a handful
of regions, and the content itself is served from Microsoft's edge everywhere
regardless, so this affects where the resource is managed rather than where
anybody downloads from.
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

resource site 'Microsoft.Web/staticSites@2024-04-01' = {
  name: name
  location: location
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {
    // No repositoryUrl and no branch. Those wire up the GitHub integration,
    // which writes a workflow into the repository and takes over deployment.
    // This is deployed from Azure DevOps with a deployment token instead, so
    // the pipeline stays the one place that decides what gets published.
    allowConfigFileUpdates: true

    // staticwebapp.config.json ships with the build and carries the routing
    // rules, so the app decides its own fallback rather than the resource.
    stagingEnvironmentPolicy: 'Enabled'
  }
}

@description('Where the site will answer once something has been deployed to it.')
output defaultHostname string = site.properties.defaultHostname

@description('For the pipeline, which needs the resource name to fetch its deployment token.')
output siteName string = site.name

// The deployment token is deliberately NOT an output. Outputs are kept in the
// deployment history and readable by anyone with access to the resource group,
// and this one is enough to publish to the site. The pipeline fetches it at
// run time instead.
