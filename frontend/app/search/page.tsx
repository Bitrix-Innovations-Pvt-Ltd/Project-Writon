'use client';

import { useEffect, useRef, useState } from 'react';
import Navbar from '@/components/shared/Navbar';
import useSWR from 'swr';
import Link from 'next/link';

const fetcher = (url: string) => fetch(url).then((res) => res.json());

const CASE_TYPES = ['Constitutional', 'Criminal', 'Civil', 'Family', 'Environmental', 'Property', 'Taxation'];
const YEAR_RANGES = [
  { label: 'Last 5 years', value: [2020, 2021, 2022, 2023, 2024, 2025] },
  { label: '2010–2019', value: [2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019] },
  { label: '2000–2009', value: [2000, 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009] },
  { label: 'Before 2000', value: [] }, // handled separately as a flag
];
const COMMON_ACTS = [
  'IPC', 'CrPC', 'CPC', 'Evidence Act', 'Constitution of India',
  'Income Tax Act', 'Companies Act', 'Arbitration Act', 'Consumer Protection Act',
];

export default function SearchPage() {
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  // Phase 1 Filters
  const [selectedCaseTypes, setSelectedCaseTypes] = useState<string[]>([]);
  const [selectedYears, setSelectedYears] = useState<number[]>([]);
  const [selectedActs, setSelectedActs] = useState<string[]>([]);
  const [showMoreFilters, setShowMoreFilters] = useState(false);

  const [page, setPage] = useState(1);
  const limit = 12;

  // Debounce search term
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchTerm);
      setPage(1);
    }, 400);
    return () => clearTimeout(timer);
  }, [searchTerm]);

  // Reset page on filter change
  useEffect(() => {
    setPage(1);
  }, [selectedCaseTypes, selectedYears, selectedActs]);

  // Construct API URL
  const queryParams = new URLSearchParams({
    page: page.toString(),
    limit: limit.toString(),
  });
  if (debouncedSearch) queryParams.append('q', debouncedSearch);
  selectedCaseTypes.forEach((ct) => queryParams.append('case_type', ct));
  selectedYears.forEach((y) => queryParams.append('year', y.toString()));
  selectedActs.forEach((a) => queryParams.append('acts_cited', a));

  const { data, error, isLoading } = useSWR(
    `http://localhost:8000/api/search/precedents?${queryParams.toString()}`,
    fetcher
  );

  // Keyboard shortcut
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  const toggleCaseType = (ct: string) => {
    setSelectedCaseTypes((prev) =>
      prev.includes(ct) ? prev.filter((x) => x !== ct) : [...prev, ct]
    );
  };

  const toggleAct = (act: string) => {
    setSelectedActs((prev) =>
      prev.includes(act) ? prev.filter((x) => x !== act) : [...prev, act]
    );
  };

  const toggleYearRange = (years: number[]) => {
    const allSelected = years.every((y) => selectedYears.includes(y));
    if (allSelected) {
      setSelectedYears((prev) => prev.filter((y) => !years.includes(y)));
    } else {
      setSelectedYears((prev) => Array.from(new Set([...prev, ...years])));
    }
  };

  const hasActiveFilters =
    selectedCaseTypes.length > 0 || selectedYears.length > 0 || selectedActs.length > 0;

  const clearAllFilters = () => {
    setSelectedCaseTypes([]);
    setSelectedYears([]);
    setSelectedActs([]);
  };

  const facets = data?.facets?.case_type || {};

  return (
    <div className="font-body-md text-on-surface bg-[#FAF9F6] min-h-screen relative selection:bg-primary-fixed selection:text-on-primary-fixed">
      {/* Paper texture background overlay */}
      <div
        className="fixed inset-0 z-0 pointer-events-none opacity-[0.03]"
        style={{ backgroundImage: 'url("https://www.transparenttextures.com/patterns/parchment.png")' }}
      />

      <div className="relative z-10 flex flex-col min-h-screen">
        <Navbar />

        <main className="flex-1 max-w-[1280px] mx-auto w-full px-4 md:px-10 py-12">
          {/* Header Section */}
          <header className="mb-10 text-center">
            <h1 className="font-display-lg text-4xl md:text-5xl font-bold text-on-background mb-4">
              Supreme Court Precedents
            </h1>
            <p className="font-body-lg text-lg text-on-surface-variant max-w-2xl mx-auto">
              {data?.total != null
                ? `${data.total.toLocaleString()} precedents`
                : 'Loading...'}{' '}
              · Binding applicability mapped to High Courts and lower courts
            </p>
          </header>

          {/* Search Bar */}
          <section className="space-y-6 mb-10 w-full">
            <div className="relative w-full group">
              <div className="absolute inset-y-0 left-4 flex items-center pointer-events-none transition-colors duration-300 group-focus-within:text-primary">
                <span className="material-symbols-outlined text-outline group-focus-within:text-primary">search</span>
              </div>
              <input
                ref={searchInputRef}
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full pl-12 pr-20 py-4 rounded-xl border border-outline-variant bg-white focus:outline-none focus:ring-4 focus:ring-primary/20 focus:border-primary transition-all duration-300 shadow-sm hover:shadow-md font-body-md"
                placeholder="Search precedents by concept, citation, or party name..."
                type="text"
                id="search-input"
              />
              <div className="absolute inset-y-0 right-4 flex items-center gap-2">
                {searchTerm && (
                  <button
                    onClick={() => setSearchTerm('')}
                    className="text-outline hover:text-on-background transition-colors"
                    title="Clear search"
                  >
                    <span className="material-symbols-outlined text-[20px]">close</span>
                  </button>
                )}
                <kbd className="hidden md:inline-flex items-center gap-1 px-2 py-1 text-xs font-semibold text-outline bg-surface-container-low rounded border border-outline-variant">
                  <span>⌘</span>K
                </kbd>
              </div>
            </div>

            {/* Filter Section */}
            <div className="w-full">
              <div className="bg-white rounded-xl border border-outline-variant p-4 shadow-sm">
                {/* Case Type Filter Row */}
                <div className="mb-4">
                  <p className="text-xs font-bold uppercase tracking-widest text-on-surface-variant mb-3 flex items-center gap-1.5">
                    <span className="material-symbols-outlined text-[14px]">category</span>
                    Case Type
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {CASE_TYPES.map((ct) => {
                      const count = facets[ct];
                      const isSelected = selectedCaseTypes.includes(ct);
                      return (
                        <button
                          key={ct}
                          id={`filter-case-type-${ct.toLowerCase()}`}
                          onClick={() => toggleCaseType(ct)}
                          className={`px-4 py-1.5 rounded-full font-label-md text-sm shrink-0 transition-all duration-300 flex items-center gap-1.5 ${
                            isSelected
                              ? 'bg-primary text-white border border-primary shadow-sm'
                              : 'bg-white text-on-surface-variant border border-outline-variant hover:border-primary hover:text-primary hover:bg-surface-container-low'
                          }`}
                        >
                          {ct}
                          {count != null && (
                            <span
                              className={`text-xs px-1.5 py-0.5 rounded-full font-bold leading-none ${
                                isSelected ? 'bg-white/20 text-white' : 'bg-surface-container-high text-on-surface-variant'
                              }`}
                            >
                              {count}
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Toggle more filters */}
                <button
                  id="toggle-more-filters"
                  onClick={() => setShowMoreFilters((v) => !v)}
                  className="text-sm font-semibold text-primary hover:underline flex items-center gap-1 transition-colors"
                >
                  <span className="material-symbols-outlined text-[16px]">
                    {showMoreFilters ? 'expand_less' : 'expand_more'}
                  </span>
                  {showMoreFilters ? 'Hide' : 'Show'} Year & Acts Filters
                </button>

                {/* Year & Acts Filters (collapsible) */}
                {showMoreFilters && (
                  <div className="mt-4 pt-4 border-t border-outline-variant space-y-4">
                    {/* Year Filter */}
                    <div>
                      <p className="text-xs font-bold uppercase tracking-widest text-on-surface-variant mb-3 flex items-center gap-1.5">
                        <span className="material-symbols-outlined text-[14px]">calendar_month</span>
                        Year Range
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {YEAR_RANGES.map(({ label, value }) => {
                          if (value.length === 0) return null; // skip "Before 2000" for now
                          const isSelected = value.every((y) => selectedYears.includes(y));
                          return (
                            <button
                              key={label}
                              id={`filter-year-${label.replace(/\s+/g, '-').toLowerCase()}`}
                              onClick={() => toggleYearRange(value)}
                              className={`px-4 py-1.5 rounded-full font-label-md text-sm shrink-0 transition-all duration-300 ${
                                isSelected
                                  ? 'bg-primary text-white border border-primary shadow-sm'
                                  : 'bg-white text-on-surface-variant border border-outline-variant hover:border-primary hover:text-primary hover:bg-surface-container-low'
                              }`}
                            >
                              {label}
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    {/* Acts Cited Filter */}
                    <div>
                      <p className="text-xs font-bold uppercase tracking-widest text-on-surface-variant mb-3 flex items-center gap-1.5">
                        <span className="material-symbols-outlined text-[14px]">menu_book</span>
                        Acts Cited
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {COMMON_ACTS.map((act) => {
                          const isSelected = selectedActs.includes(act);
                          return (
                            <button
                              key={act}
                              id={`filter-act-${act.replace(/\s+/g, '-').toLowerCase()}`}
                              onClick={() => toggleAct(act)}
                              className={`px-4 py-1.5 rounded-full font-label-md text-sm shrink-0 transition-all duration-300 ${
                                isSelected
                                  ? 'bg-primary text-white border border-primary shadow-sm'
                                  : 'bg-white text-on-surface-variant border border-outline-variant hover:border-primary hover:text-primary hover:bg-surface-container-low'
                              }`}
                            >
                              {act}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                )}

                {/* Active Filters + Clear */}
                {hasActiveFilters && (
                  <div className="mt-4 pt-4 border-t border-outline-variant flex items-center gap-3 flex-wrap">
                    <span className="text-xs font-semibold text-on-surface-variant">Active:</span>
                    {selectedCaseTypes.map((ct) => (
                      <span
                        key={ct}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-primary/10 text-primary"
                      >
                        {ct}
                        <button onClick={() => toggleCaseType(ct)} className="hover:text-error transition-colors">
                          <span className="material-symbols-outlined text-[13px]">close</span>
                        </button>
                      </span>
                    ))}
                    {selectedYears.length > 0 && (
                      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-primary/10 text-primary">
                        {selectedYears.length} year{selectedYears.length !== 1 ? 's' : ''}
                        <button
                          onClick={() => setSelectedYears([])}
                          className="hover:text-error transition-colors"
                        >
                          <span className="material-symbols-outlined text-[13px]">close</span>
                        </button>
                      </span>
                    )}
                    {selectedActs.map((act) => (
                      <span
                        key={act}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-primary/10 text-primary"
                      >
                        {act}
                        <button onClick={() => toggleAct(act)} className="hover:text-error transition-colors">
                          <span className="material-symbols-outlined text-[13px]">close</span>
                        </button>
                      </span>
                    ))}
                    <button
                      id="clear-all-filters"
                      onClick={clearAllFilters}
                      className="ml-auto text-xs font-bold text-error hover:underline"
                    >
                      Clear all
                    </button>
                  </div>
                )}
              </div>
            </div>
          </section>

          {/* Precedents Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 animate-fade-slide-up">
            {isLoading && (
              <div className="col-span-full py-20 text-center text-outline font-body-lg">
                <span className="material-symbols-outlined animate-spin text-4xl mb-4 text-primary block">autorenew</span>
                <p>Searching through judgments...</p>
              </div>
            )}

            {error && (
              <div className="col-span-full py-20 text-center text-error font-body-lg">
                <p>Failed to load precedents from the database. Please ensure backend is running.</p>
              </div>
            )}

            {!isLoading && !error && data?.items?.length === 0 && (
              <div className="col-span-full py-20 text-center text-outline font-body-lg">
                <span className="material-symbols-outlined text-4xl mb-4 block text-outline">search_off</span>
                <p>No precedents found matching your search.</p>
                {hasActiveFilters && (
                  <button onClick={clearAllFilters} className="mt-4 text-sm font-semibold text-primary hover:underline">
                    Clear filters and try again
                  </button>
                )}
              </div>
            )}

            {!isLoading &&
              !error &&
              data?.items?.map((item: any, i: number) => (
                <Link
                  key={item.id}
                  href={`/judgment/${item.id}`}
                  id={`judgment-card-${item.id}`}
                  className={`group relative bg-white p-6 rounded-xl border transition-all duration-300 hover:-translate-y-1 cursor-pointer block ${
                    i === 0 && page === 1 && debouncedSearch
                      ? 'border-2 border-[#fdc34d] hover:shadow-[0_12px_28px_rgba(123,88,0,0.15)] hover:border-[#7b5800]'
                      : 'border-outline-variant hover:shadow-[0_8px_24px_rgba(14,107,82,0.12)] hover:border-primary'
                  }`}
                >
                  {i === 0 && page === 1 && debouncedSearch && (
                    <div className="absolute -top-3 left-6">
                      <span className="bg-[#7b5800] text-white text-xs px-3 py-1 rounded-full shadow-sm uppercase tracking-widest transition-colors group-hover:bg-[#5d4200]">
                        Most Relevant
                      </span>
                    </div>
                  )}
                  <div className="flex justify-between items-start mb-4 pt-2">
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-surface-container-high text-primary">
                      {item.court} ({item.year})
                    </span>
                    <span className="text-outline group-hover:text-primary transition-colors">
                      <span className="material-symbols-outlined">open_in_new</span>
                    </span>
                  </div>
                  <h3
                    className="font-display-lg text-[20px] font-semibold text-on-background mb-3 leading-snug group-hover:text-primary transition-colors line-clamp-2"
                    title={item.title}
                  >
                    {item.title}
                  </h3>
                  <span className="inline-block px-2 py-1 rounded bg-primary-fixed text-on-primary-fixed text-[12px] font-semibold uppercase mb-4 tracking-wider truncate max-w-full">
                    {item.case_type}
                  </span>
                  <p className="text-on-surface-variant font-body-md line-clamp-3 mb-4 italic">
                    &ldquo;{item.summary || item.holding || 'No summary available for this judgment.'}&rdquo;
                  </p>
                  <div className="flex items-center gap-2 pt-4 border-t border-outline-variant transition-colors duration-300 group-hover:border-primary/20">
                    <span className="material-symbols-outlined text-[16px] text-outline">gavel</span>
                    <span className="text-xs font-semibold text-outline truncate" title={item.binding_on}>
                      Binding on: {item.binding_on}
                    </span>
                  </div>
                </Link>
              ))}
          </div>

          {/* Pagination */}
          {!isLoading && !error && data?.total_pages > 1 && (
            <div className="mt-16 flex justify-center items-center gap-4">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="p-2 rounded-lg border border-outline-variant hover:bg-surface-container-low transition-colors disabled:opacity-50 text-on-surface"
              >
                <span className="material-symbols-outlined">chevron_left</span>
              </button>

              <div className="flex gap-2">
                <button className="w-10 h-10 rounded-lg bg-primary text-white text-sm font-semibold">{page}</button>
                <span className="text-on-surface self-center px-2">of {data.total_pages}</span>
              </div>

              <button
                onClick={() => setPage((p) => Math.min(data.total_pages, p + 1))}
                disabled={page === data.total_pages}
                className="p-2 rounded-lg border border-outline-variant hover:bg-surface-container-low transition-colors disabled:opacity-50 text-on-surface"
              >
                <span className="material-symbols-outlined">chevron_right</span>
              </button>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
