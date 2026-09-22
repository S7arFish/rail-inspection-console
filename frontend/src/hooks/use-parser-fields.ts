import { useQuery } from '@tanstack/react-query'
import { fetchParserFields } from '@/lib/data-source'

export function useParserFields() {
  return useQuery({
    queryKey: ['parser', 'fields'],
    queryFn: fetchParserFields,
    staleTime: 5 * 60 * 1000,
  })
}

export function useFieldLookup() {
  const { data } = useParserFields()
  return (name: string) => data?.fields.find((f) => f.name === name)
}
