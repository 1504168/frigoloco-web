import { Construction } from 'lucide-react'
import { PageHeader } from '@/components/shared/PageHeader'
import { Card, CardContent } from '@/components/ui/card'

export interface PlaceholderPageProps {
  breadcrumb?: string
  title: string
  description?: string
}

/**
 * Minimal working page used as the example in each domain's routes.tsx and as a
 * temporary stand-in for not-yet-built nav routes. A domain page-agent replaces
 * these with real pages.
 */
export function PlaceholderPage({ breadcrumb, title, description }: PlaceholderPageProps) {
  return (
    <div className="space-y-6">
      <PageHeader breadcrumb={breadcrumb} title={title} description={description} />
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-3 py-16 text-center">
          <Construction className="h-9 w-9 text-muted-foreground" />
          <div className="text-sm font-semibold text-foreground">{title} page coming soon</div>
          <p className="max-w-md text-sm text-muted-foreground">
            This route is wired into the app shell. A domain page-agent will build the
            real screen here.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
