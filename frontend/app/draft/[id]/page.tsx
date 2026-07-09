'use client';

import { useState, useEffect, useRef } from 'react';
import Navbar from '@/components/shared/Navbar';
import { useAuth } from '@clerk/nextjs';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';

import { districtCourtsData, tribunalsData, specialCourtsData } from './courtsData';

const indianStates = Object.keys(districtCourtsData).sort();

const getDistrictCourtsForState = (state: string) => {
  if (!state) return [];
  return districtCourtsData[state] || [];
};

const getFallbackDocTypes = (level: string): string[] => {
  switch (level) {
    case 'supreme':
      return [
        'Writ Petition (Art. 32)',
        'Special Leave Petition',
        'Transfer Petition',
        'Review Petition',
        'Curative Petition',
        'Original Suit (Art. 131)'
      ];
    case 'high':
      return [
        'Writ Petition (Civil)',
        'Writ Petition (Criminal)',
        'Public Interest Litigation (PIL)',
        'Criminal Appeal',
        'Civil Appeal',
        'Bail Application'
      ];
    case 'district':
      return [
        'Civil Suit (Money Recovery)',
        'Civil Suit (Partition)',
        'Criminal Complaint',
        'Bail Application (Sessions)',
        'Cheque Bounce Complaint'
      ];
    case 'tribunal':
      return [
        'Insolvency Application (Sec. 7/9/10 IBC)',
        'Company Petition',
        'Service Matter Original Application',
        'Consumer Complaint'
      ];
    case 'special_court':
      return [
        'Divorce Petition',
        'Custody Petition',
        'Commercial Suit',
        'Bail Application'
      ];
    default:
      return ['Petition', 'Appeal', 'Application'];
  }
};

export default function DraftWizard({ params }: { params: { id: string } }) {
  const { userId } = useAuth();
  const [currentStep, setCurrentStep] = useState(1);
  const [courtLevel, setCourtLevel] = useState('supreme');
  const [documentType, setDocumentType] = useState('');
  const [subjectMatter, setSubjectMatter] = useState('');
  const [caseDescription, setCaseDescription] = useState('');
  const [factsOfCase, setFactsOfCase] = useState('');
  const [grounds, setGrounds] = useState('');
  const [reliefSought, setReliefSought] = useState('');
  const [uploadedDocs, setUploadedDocs] = useState<Record<string, string>>({}); 
  const [uploadError, setUploadError] = useState<string | null>(null); 
  
  // Citations State
  const [suggestedJudgments, setSuggestedJudgments] = useState<any[]>([]);
  const [suggestedStatutes, setSuggestedStatutes] = useState<any[]>([]);
  const [selectedJudgmentIds, setSelectedJudgmentIds] = useState<Set<number>>(new Set());
  const [selectedStatuteIds, setSelectedStatuteIds] = useState<Set<number>>(new Set());
  const [isLoadingCitations, setIsLoadingCitations] = useState(false); 
  
  // New Hierarchy States
  const [selectedCategory, setSelectedCategory] = useState<any>(null);
  const [selectedCaseType, setSelectedCaseType] = useState<any>(null);
  const [selectedSubCategory, setSelectedSubCategory] = useState<any>(null);

  const [categoriesList, setCategoriesList] = useState<any[]>([]);
  const [caseTypesList, setCaseTypesList] = useState<any[]>([]);
  const [subCategoriesList, setSubCategoriesList] = useState<any[]>([]);
  
  const [isLoadingCategories, setIsLoadingCategories] = useState(false);
  const [isLoadingCaseTypes, setIsLoadingCaseTypes] = useState(false);
  const [isLoadingSubCategories, setIsLoadingSubCategories] = useState(false);
  
  // Step 5: Parties & Facts State
  const [advocateName, setAdvocateName] = useState('');
  const [advocateEnrollmentNo, setAdvocateEnrollmentNo] = useState('');
  const [petitioners, setPetitioners] = useState<string[]>(['']);
  const [respondents, setRespondents] = useState<string[]>(['']);
  const [impugnedOrderDate, setImpugnedOrderDate] = useState('');
  const [jurisdictionBasis, setJurisdictionBasis] = useState('');
  const [interimReliefSought, setInterimReliefSought] = useState('');

  const [selectedHighCourt, setSelectedHighCourt] = useState('');
  const [selectedHighCourtBench, setSelectedHighCourtBench] = useState('');
  const [selectedState, setSelectedState] = useState('');
  const [selectedDistrictCourt, setSelectedDistrictCourt] = useState('');
  const [selectedSubLevel, setSelectedSubLevel] = useState<'tribunal' | 'special_court' | ''>('');
  const [selectedTribunal, setSelectedTribunal] = useState('');
  const [selectedSpecialCourt, setSelectedSpecialCourt] = useState('');
  const [documentTypes, setDocumentTypes] = useState<string[]>([]);
  const [subjectMattersList, setSubjectMattersList] = useState<{matter_name: string, applicable_doc_types: string[]}[]>([]);
  
  const [requiredDocsList, setRequiredDocsList] = useState<any[]>([]);
  const [optionalDocsList, setOptionalDocsList] = useState<any[]>([]);
  const [isLoadingDocs, setIsLoadingDocs] = useState(false);
  const [isLoadingDocTypes, setIsLoadingDocTypes] = useState(false);
  const [isLoadingSubjectMatters, setIsLoadingSubjectMatters] = useState(false);

  const [highCourtsApiData, setHighCourtsApiData] = useState<any[]>([]);

  useEffect(() => {
    const fetchHighCourts = async () => {
      try {
        const res = await fetch('/api/v1/courts/high-courts');
        const data = await res.json();
        setHighCourtsApiData(data);
      } catch (err) {
        console.error("Failed to fetch high courts", err);
      }
    };
    fetchHighCourts();
  }, []);

  // Generation state
  const [generateStatus, setGenerateStatus] = useState<'idle' | 'loading' | 'streaming' | 'completed'>('idle');
  const [generateStatusText, setGenerateStatusText] = useState('Generating your draft...');
  const [draftContent, setDraftContent] = useState('');
  const [isEditingMode, setIsEditingMode] = useState(false);
  const [htmlPages, setHtmlPages] = useState<string[]>([]);
  const [hasEdited, setHasEdited] = useState(false);
  const pageRefs = useRef<(HTMLDivElement | null)[]>([]);
  const [citations, setCitations] = useState<{citation: string, type: string, status: string}[]>([]);
  const editorRef = useRef<HTMLDivElement>(null);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>, docName: string) => {
    if (!e.target.files?.length) return;
    const file = e.target.files[0];
    
    // Check file size (5MB limit)
    if (file.size > 5 * 1024 * 1024) {
      setUploadError("File size exceeds 5MB limit.");
      return;
    }
    
    setDocStatus(docName, 'uploading');
    
    const formData = new FormData();
    formData.append("file", file);
    formData.append("draft_id", params?.id || "0");
    formData.append("doc_type", docName);
    formData.append("user_id", userId || "");
    
    try {
      const res = await fetch(`/api/v1/uploads`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const errData = await res.json();
        setUploadError(errData.detail || "Upload failed");
        setDocStatus(docName, '');
        return;
      }
      setDocStatus(docName, 'uploaded');
    } catch (err) {
      console.error(err);
      setUploadError("Network error during upload");
      setDocStatus(docName, '');
    }
  };

  const setDocStatus = (id: string, status: string) => {
    setUploadedDocs(prev => ({ ...prev, [id]: status }));
  };

  // Fetch document types dynamically from API
  useEffect(() => {
    const fetchDocumentTypes = async () => {
      let level = courtLevel;
      let name = '';

      if (courtLevel === 'supreme') {
        level = 'supreme';
      } else if (courtLevel === 'high') {
        level = 'high';
      } else if (courtLevel === 'district') {
        level = 'district';
      } else if (courtLevel === 'tribunal') {
        if (selectedSubLevel === 'special_court') {
          level = 'special_court';
          name = selectedSpecialCourt;
        } else {
          level = 'tribunal';
          name = selectedTribunal;
        }
      }

      try {
        setIsLoadingDocTypes(true);
        let url = `/api/v1/document-types/?court_level=${level}`;
        if (name) {
          url += `&tribunal_name=${encodeURIComponent(name)}`;
        }
        
        const res = await fetch(url);
        if (!res.ok) throw new Error("Failed to fetch document types");
        const data = await res.json();
        
        if (data && data.length > 0) {
          setDocumentTypes(data.map((dt: any) => dt.doc_type_name));
        } else {
          setDocumentTypes(getFallbackDocTypes(level));
        }
      } catch (error) {
        console.error("Error fetching document types:", error);
        setDocumentTypes(getFallbackDocTypes(level));
      } finally {
        setIsLoadingDocTypes(false);
      }
    };

    fetchDocumentTypes();
  }, [courtLevel, selectedSubLevel, selectedTribunal, selectedSpecialCourt]);

  // Reset selected document type when the list of available document types changes
  useEffect(() => {
    if (documentTypes.length > 0 && !documentTypes.includes(documentType)) {
      setDocumentType('');
    }
  }, [documentTypes]);

  // Fetch subject matters dynamically from API
  useEffect(() => {
    const fetchSubjectMatters = async () => {
      let level = courtLevel;
      let name = '';

      if (courtLevel === 'supreme') {
        level = 'supreme';
      } else if (courtLevel === 'high') {
        level = 'high';
      } else if (courtLevel === 'district') {
        level = 'district';
      } else if (courtLevel === 'tribunal') {
        if (selectedSubLevel === 'special_court') {
          level = 'special_court';
          name = selectedSpecialCourt;
        } else {
          level = 'tribunal';
          name = selectedTribunal;
        }
      }

      try {
        setIsLoadingSubjectMatters(true);
        let url = `/api/v1/subject-matters/?court_level=${level}`;
        if (name) {
          url += `&tribunal_name=${encodeURIComponent(name)}`;
        }
        
        const res = await fetch(url);
        if (!res.ok) throw new Error("Failed to fetch subject matters");
        const data = await res.json();
        
        if (data && data.length > 0) {
          setSubjectMattersList(data.map((sm: any) => ({
            matter_name: sm.matter_name,
            applicable_doc_types: sm.applicable_doc_types || []
          })));
        } else {
          setSubjectMattersList([]);
        }
      } catch (error) {
        console.error("Error fetching subject matters:", error);
        setSubjectMattersList([]);
      } finally {
        setIsLoadingSubjectMatters(false);
      }
    };

    fetchSubjectMatters();
  }, [courtLevel, selectedSubLevel, selectedTribunal, selectedSpecialCourt]);

  // Reset selected subject matter if it's no longer in the fetched list, 
  // BUT only if we are using the old fallback UI (categoriesList is empty or fake).
  useEffect(() => {
    const isUsingOldUI = !categoriesList.length || (selectedCategory && selectedCategory.id >= 1000);
    if (isUsingOldUI && subjectMatter && subjectMattersList.length > 0) {
      // Only clear if it's not in the old list and not a custom text (since they can type anything if list is empty, but if list > 0 they must select)
      if (!subjectMattersList.some(sm => sm.matter_name === subjectMatter)) {
        // If they typed something manually ("Other"), don't clear it immediately, but for now we just check
        // if it's not in the list. Wait, in the old UI they can't type if list > 0.
        setSubjectMatter('');
      }
    }
  }, [subjectMattersList, categoriesList, selectedCategory, subjectMatter]);


  // ------------- NEW HIERARCHY HOOKS -------------
  useEffect(() => {
    const fetchCategories = async () => {
      let level = courtLevel;
      if (level === 'tribunal' && selectedSubLevel === 'special_court') {
        level = 'special_court';
      }
      try {
        setIsLoadingCategories(true);
        const res = await fetch(`/api/v1/hierarchy/categories?court_level=${level}`);
        if (res.ok) {
          const data = await res.json();
          setCategoriesList(data);
          
          // If no categories, fallback to documentTypes array for UI mapping
          if (data.length === 0 && documentTypes.length > 0) {
             const fakeCats = documentTypes.map((dt, i) => ({ id: i+1000, name: dt }));
             setCategoriesList(fakeCats);
          }
        }
      } catch (err) {
        console.error(err);
      } finally {
        setIsLoadingCategories(false);
      }
    };
    fetchCategories();
  }, [courtLevel, selectedSubLevel, documentTypes]);

  useEffect(() => {
    if (!selectedCategory) {
      setCaseTypesList([]);
      return;
    }
    const fetchCaseTypes = async () => {
      // If it's a fallback fake category, just set caseTypes to empty
      if (selectedCategory.id >= 1000) {
         setCaseTypesList([]);
         return;
      }
      try {
        setIsLoadingCaseTypes(true);
        const res = await fetch(`/api/v1/hierarchy/case-types?category_id=${selectedCategory.id}`);
        if (res.ok) {
          const data = await res.json();
          setCaseTypesList(data);
        }
      } catch (err) {
        console.error(err);
      } finally {
        setIsLoadingCaseTypes(false);
      }
    };
    fetchCaseTypes();
  }, [selectedCategory]);

  useEffect(() => {
    if (!selectedCaseType) {
      setSubCategoriesList([]);
      return;
    }
    const fetchSubCategories = async () => {
      try {
        setIsLoadingSubCategories(true);
        const res = await fetch(`/api/v1/hierarchy/sub-categories?case_type_id=${selectedCaseType.id}`);
        if (res.ok) {
          const data = await res.json();
          setSubCategoriesList(data);
        }
      } catch (err) {
        console.error(err);
      } finally {
        setIsLoadingSubCategories(false);
      }
    };
    fetchSubCategories();
  }, [selectedCaseType]);
  // -----------------------------------------------

  // Fetch document requirements when entering Step 4
  useEffect(() => {
    if (currentStep !== 4 || !subjectMatter) return;

    const fetchDocumentRequirements = async () => {
      try {
        setIsLoadingDocs(true);
        let level = courtLevel;
        if (level === 'tribunal' && selectedSubLevel === 'special_court') {
          level = 'special_court';
        }
        
        const url = `/api/v1/document-requirements/?court_level=${level}&subject_matter=${encodeURIComponent(subjectMatter)}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error("Failed to fetch document requirements");
        
        const data = await res.json();
        const required = data.filter((d: any) => d.requirement_type === 'required');
        const optional = data.filter((d: any) => d.requirement_type === 'optional');
        
        setRequiredDocsList(required);
        setOptionalDocsList(optional);
      } catch (error) {
        console.error("Error fetching docs:", error);
      } finally {
        setIsLoadingDocs(false);
      }
    };

    fetchDocumentRequirements();
  }, [currentStep, courtLevel, selectedSubLevel, subjectMatter]);

  const steps = [
    { num: 1, label: 'Court & Level' },
    { num: 2, label: 'Document Type' },
    { num: 3, label: 'Subject Matter' },
    { num: 4, label: 'Documents' },
    { num: 5, label: 'Parties & Facts' },
    { num: 6, label: 'Citations' },
    { num: 7, label: 'Generate' },
  ];

  const totalDocs = requiredDocsList.length + optionalDocsList.length;
  const confirmedDocs = Object.keys(uploadedDocs).length;

  const handleNext = async () => {
    if (currentStep === 3 && subjectMatter === 'Other') {
      try {
        let level = courtLevel;
        if (level === 'tribunal' && selectedSubLevel === 'special_court') {
          level = 'special_court';
        }
        await fetch('/api/v1/analytics/subject-matter', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            court_level: level,
            selected_other: true,
            case_description_snippet: caseDescription
          })
        });
      } catch (e) {
        console.error("Failed to log analytics", e);
      }
    }

    if (currentStep === 5) {
      setCurrentStep(6);
      fetchCitations();
    } else if (currentStep < 7) {
      setCurrentStep(currentStep + 1);
      if (currentStep + 1 === 7) {
        startGeneration();
      }
    }
  };

  const fetchCitations = async () => {
    setIsLoadingCitations(true);
    setSuggestedJudgments([]);
    setSuggestedStatutes([]);
    
    const courtDisplay =
      courtLevel === 'high' && selectedHighCourt ? `${selectedHighCourt}${selectedHighCourtBench ? ` - ${selectedHighCourtBench}` : ''}` :
      courtLevel === 'district' && selectedDistrictCourt ? `${selectedDistrictCourt} District Court, ${selectedState}` :
      courtLevel === 'tribunal' && selectedTribunal ? selectedTribunal :
      courtLevel === 'tribunal' && selectedSpecialCourt ? selectedSpecialCourt :
      `${courtLevel.charAt(0).toUpperCase() + courtLevel.slice(1)} Court of India`;

    const body = {
      court_level: courtLevel,
      court_display: courtDisplay,
      document_type: documentType,
      subject_matter: subjectMatter,
      case_description: caseDescription,
      facts_of_case: factsOfCase,
      grounds: grounds,
      relief_sought: reliefSought,
      interim_relief_sought: interimReliefSought,
      advocate_name: advocateName,
      advocate_enrollment_no: advocateEnrollmentNo,
      petitioners: petitioners.filter(p => p.trim()),
      respondents: respondents.filter(r => r.trim()),
      jurisdiction_basis: jurisdictionBasis,
      impugned_order_date: impugnedOrderDate || null,
      draft_id: params?.id ? parseInt(params.id) : undefined
    };

    try {
      const res = await fetch('/api/v1/drafts/suggest-citations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (res.ok) {
        const data = await res.json();
        setSuggestedJudgments(data.judgments || []);
        setSuggestedStatutes(data.statutes || []);
        
        // Select all by default
        setSelectedJudgmentIds(new Set((data.judgments || []).map((j: any) => j.id)));
        setSelectedStatuteIds(new Set((data.statutes || []).map((s: any) => s.id)));
      } else {
        console.error("Failed to fetch citations:", await res.text());
        alert("Failed to fetch citations from the server.");
      }
    } catch (err) {
      console.error(err);
      alert("Network error while fetching citations.");
    } finally {
      setIsLoadingCitations(false);
    }
  };

  const handleBack = () => {
    if (currentStep > 1) setCurrentStep(currentStep - 1);
  };

  const startGeneration = async () => {
    setGenerateStatus('loading');
    setGenerateStatusText('Preparing AI models...');
    setDraftContent('');
    setCitations([]);

    const courtDisplay =
      courtLevel === 'high' && selectedHighCourt ? `${selectedHighCourt}${selectedHighCourtBench ? ` - ${selectedHighCourtBench}` : ''}` :
      courtLevel === 'district' && selectedDistrictCourt ? `${selectedDistrictCourt} District Court, ${selectedState}` :
      courtLevel === 'tribunal' && selectedTribunal ? selectedTribunal :
      courtLevel === 'tribunal' && selectedSpecialCourt ? selectedSpecialCourt :
      `${courtLevel.charAt(0).toUpperCase() + courtLevel.slice(1)} Court of India`;

    const body = {
      court_level: courtLevel,
      court_display: courtDisplay,
      document_type: documentType,
      subject_matter: subjectMatter,
      case_description: caseDescription,
      facts_of_case: '',
      grounds: '',
      relief_sought: '',
      interim_relief_sought: interimReliefSought,
      advocate_name: advocateName,
      advocate_enrollment_no: advocateEnrollmentNo,
      petitioners: petitioners.filter(p => p.trim()),
      respondents: respondents.filter(r => r.trim()),
      jurisdiction_basis: jurisdictionBasis,
      impugned_order_date: impugnedOrderDate || null,
      selected_judgments: suggestedJudgments.filter(j => selectedJudgmentIds.has(j.id)),
      selected_statutes: suggestedStatutes.filter(s => selectedStatuteIds.has(s.id)),
      draft_id: params?.id ? parseInt(params.id) : undefined
    };

    try {
      const response = await fetch('/api/v1/drafts/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        setGenerateStatus('completed');
        setGenerateStatusText('Generation failed.');
        return;
      }

      const reader = response.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      setGenerateStatus('streaming');

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('event: status')) continue;
          if (line.startsWith('event: token')) continue;
          if (line.startsWith('event: citations')) continue;
          if (line.startsWith('event: done')) {
            setGenerateStatus('completed');
            setGenerateStatusText('Generation Complete');
          }
          if (line.startsWith('data: ')) {
            const raw = line.slice(6);
            // Try to detect which event type this data belongs to by looking at prev lines
            try {
              const parsed = JSON.parse(raw);
              if (Array.isArray(parsed)) {
                // citations event
                setCitations(parsed);
              } else if (typeof parsed === 'string') {
                // token event
                setDraftContent(prev => prev + parsed);
                if (editorRef.current) {
                  editorRef.current.scrollTop = editorRef.current.scrollHeight;
                }
              }
            } catch {
              // status text or plain data
              if (raw !== 'complete' && !raw.startsWith('{')) {
                setGenerateStatusText(raw);
              }
            }
          }
        }
      }
    } catch (err) {
      console.error('Generation error:', err);
      setGenerateStatus('completed');
      setGenerateStatusText('Generation failed — check console.');
    }
  };

  const handleFormat = (command: string) => {
    document.execCommand(command, false, undefined);
  };

  const handleDownloadWord = () => {
    if (!editorRef.current) return;
    
    // Construct footer string
    const advName = advocateName || "____________________";
    const advEnroll = advocateEnrollmentNo || "_______________";
    const footerHtml = `
      <br/><br/>
      <table style="width: 100%; border: none; font-family: 'Times New Roman', Times, serif; font-size: 12pt; margin-top: 50px;">
        <tr>
          <td style="width: 50%; vertical-align: bottom;">
            PLACE: ______________<br/>
            DATED: ______________
          </td>
          <td style="width: 50%; text-align: right; vertical-align: bottom;">
            <b>(${advName.toUpperCase()})</b><br/>
            Advocate<br/>
            Enrollment No. ${advEnroll}<br/>
            Counsel for Petitioner
          </td>
        </tr>
      </table>
      <br clear="all" style="page-break-before:always" />
    `;

    // Extract pages and append footer
    let finalHtml = "";
    const pages = editorRef.current.children;
    for (let i = 0; i < pages.length; i++) {
      finalHtml += pages[i].innerHTML;
      if (i < pages.length - 1) {
         finalHtml += footerHtml;
      } else {
         finalHtml += footerHtml.replace('<br clear="all" style="page-break-before:always" />', '');
      }
    }
    
    const header = "<html xmlns:o='urn:schemas-microsoft-com:office:office' xmlns:w='urn:schemas-microsoft-com:office:word' xmlns='http://www.w3.org/TR/REC-html40'><head><meta charset='utf-8'><title>Draft Document</title></head><body>";
    const footer = "</body></html>";
    const html = header + finalHtml + footer;
    const blob = new Blob(['\ufeff', html], { type: 'application/msword' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `Draft_Petition_${new Date().toISOString().split('T')[0]}.doc`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleDownloadPDF = () => {
    window.print();
  };

  const addPetitioner = () => setPetitioners([...petitioners, '']);
  const updatePetitioner = (index: number, value: string) => {
    const newPetitioners = [...petitioners];
    newPetitioners[index] = value;
    setPetitioners(newPetitioners);
  };
  const removePetitioner = (index: number) => {
    if (petitioners.length > 1) {
      setPetitioners(petitioners.filter((_, i) => i !== index));
    }
  };

  const addRespondent = () => setRespondents([...respondents, '']);
  const updateRespondent = (index: number, value: string) => {
    const newRespondents = [...respondents];
    newRespondents[index] = value;
    setRespondents(newRespondents);
  };
  const removeRespondent = (index: number) => {
    if (respondents.length > 1) {
      setRespondents(respondents.filter((_, i) => i !== index));
    }
  };

  return (
    <div className="font-body-md text-body-md bg-surface min-h-screen text-on-surface flex flex-col relative">
      {/* Toast Notification */}
      {uploadError && (
        <div className="fixed top-24 right-6 z-[100] animate-in fade-in slide-in-from-top-4 duration-300">
          <div className="bg-[#1A1A1A] border-l-4 border-error text-white shadow-xl rounded-lg p-4 max-w-sm flex flex-col gap-2 ring-1 ring-white/10">
            <div className="flex justify-between items-start gap-4">
              <div className="flex items-start gap-3">
                <span className="material-symbols-outlined text-error mt-0.5">error</span>
                <div>
                  <h3 className="font-bold text-sm text-white">Upload Failed</h3>
                  <p className="text-sm text-gray-300 mt-1 leading-relaxed">{uploadError}</p>
                </div>
              </div>
              <button onClick={() => setUploadError(null)} className="text-gray-400 hover:text-white transition-colors shrink-0">
                <span className="material-symbols-outlined text-sm">close</span>
              </button>
            </div>
          </div>
        </div>
      )}
      <Navbar />

      <main className={`flex-1 flex flex-col ${currentStep === 7 && generateStatus !== 'idle' && generateStatus !== 'loading' ? 'max-w-6xl w-full mx-auto px-4 py-8 print:p-0 print:m-0 print:max-w-none print:block' : 'max-w-[900px] mx-auto py-12 px-4 md:px-0'}`}>
        
        {/* Hide header and stepper if we are in the editor view */}
        {!(currentStep === 7 && generateStatus !== 'loading' && generateStatus !== 'idle') && (
          <>
            {/* Header Section */}
            <div className="text-center mb-10">
              <h1 className="font-display-lg text-4xl mb-2">AI Legal Document Drafting</h1>
              <p className="font-body-lg text-lg text-on-surface-variant">Fill in the details below and Writon will draft your complete legal document</p>
            </div>

            {/* Stepper Component */}
            <div className="flex items-center justify-between mb-12 relative max-w-3xl mx-auto">
              {steps.map((step, index) => (
                <div key={step.num} className="flex-1 flex items-center">
                  <div className="flex flex-col items-center gap-2 z-10 step-node relative w-full">
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center font-bold border-2 transition-colors ${currentStep > step.num ? 'bg-primary text-white border-primary' : currentStep === step.num ? 'bg-primary text-white border-primary shadow-[0_0_0_4px_rgba(14,107,82,0.1)]' : 'bg-surface-container-lowest text-outline border-outline-variant'}`}>
                      {currentStep > step.num ? <span className="material-symbols-outlined text-xl">check</span> : step.num}
                    </div>
                    <span className={`font-label-sm text-xs font-bold mt-1 transition-colors ${currentStep >= step.num ? 'text-primary' : 'text-on-surface-variant'}`}>{step.label}</span>
                  </div>
                  {index < steps.length - 1 && (
                    <div className={`h-[2px] flex-grow mx-1 transition-colors duration-500 ${currentStep > step.num ? 'bg-primary' : 'bg-outline-variant/40'}`}></div>
                  )}
                </div>
              ))}
            </div>
          </>
        )}

        {/* Content Area */}
        <div className={`animate-fade-slide-up print:animate-none print:transform-none bg-white rounded-2xl shadow-sm border border-outline-variant ${currentStep === 7 && generateStatus !== 'loading' && generateStatus !== 'idle' ? 'flex-1 flex flex-col overflow-hidden print:overflow-visible print:border-none print:shadow-none' : 'p-8 md:p-10 space-y-6'}`}>
          
          {currentStep === 1 && (
            <>
              <div className="mb-8">
                <h2 className="font-display-lg text-2xl font-bold text-on-surface mb-1">Select Court Level</h2>
                <p className="text-on-surface-variant text-sm">Choose the jurisdiction for your legal document.</p>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {[
                  { id: 'supreme', icon: 'balance', title: 'Supreme Court of India', desc: 'Appellate jurisdiction for constitutional matters and Special Leave Petitions.' },
                  { id: 'high', icon: 'account_balance_wallet', title: 'High Court', desc: 'Writ jurisdiction under Article 226 and appellate review.' },
                  { id: 'district', icon: 'home_work', title: 'District / Sessions Court', desc: 'Primary civil and criminal trials.' },
                  { id: 'tribunal', icon: 'assignment_late', title: 'Tribunal / Special Court', desc: 'Specialized bodies like NCLT, NGT, etc.' }
                ].map((court) => (
                  <label key={court.id} className={`court-card group cursor-pointer relative bg-white p-6 border rounded-xl hover:shadow-md transition-all duration-300 ${courtLevel === court.id ? 'border-primary border-2 bg-primary/5 shadow-[0_0_0_4px_rgba(14,107,82,0.1)]' : 'border-outline-variant hover:border-primary/50'}`} onClick={() => setCourtLevel(court.id)}>
                    <input type="radio" name="court_level" value={court.id} checked={courtLevel === court.id} onChange={() => setCourtLevel(court.id)} className="hidden" />
                    <div className="flex justify-between items-start mb-4">
                      <span className={`material-symbols-outlined text-3xl transition-colors ${courtLevel === court.id ? 'text-primary' : 'text-outline group-hover:text-primary'}`}>{court.icon}</span>
                      <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center transition-colors ${courtLevel === court.id ? 'border-primary' : 'border-outline-variant group-hover:border-primary/50'}`}>
                        <div className={`w-2.5 h-2.5 rounded-full transition-colors ${courtLevel === court.id ? 'bg-primary' : 'bg-transparent'}`}></div>
                      </div>
                    </div>
                    <h3 className={`font-semibold uppercase tracking-wider mb-2 transition-colors ${courtLevel === court.id ? 'text-primary' : 'text-on-surface'}`}>{court.title}</h3>
                    <p className="text-on-surface-variant text-sm leading-relaxed">{court.desc}</p>
                  </label>
                ))}
              </div>

              {courtLevel === 'high' && (
                <div className="mt-6 p-6 border rounded-xl bg-surface-container-lowest animate-fade-slide-up space-y-4">
                  <div>
                    <h3 className="font-bold text-on-surface mb-2">Select High Court</h3>
                    <select 
                      value={selectedHighCourt}
                      onChange={(e) => {
                        setSelectedHighCourt(e.target.value);
                        setSelectedHighCourtBench('');
                      }}
                      className="w-full p-3 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm bg-white"
                    >
                      <option value="" disabled>Choose a High Court...</option>
                      {highCourtsApiData.map((court) => (
                        <option key={court.id} value={court.name}>{court.name}</option>
                      ))}
                    </select>
                  </div>
                  
                  {selectedHighCourt && (
                    <div className="animate-fade-slide-up">
                      <h3 className="font-bold text-on-surface mb-2">Select Bench / Seat</h3>
                      <select 
                        value={selectedHighCourtBench}
                        onChange={(e) => setSelectedHighCourtBench(e.target.value)}
                        className="w-full p-3 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm bg-white"
                      >
                        <option value="" disabled>Choose a Bench...</option>
                        {(() => {
                          const hc = highCourtsApiData.find(c => c.name === selectedHighCourt);
                          if (!hc) return null;
                          return (
                            <>
                              {hc.benches.map((bench: any) => (
                                <option key={bench.id} value={bench.name}>
                                  {bench.name}
                                </option>
                              ))}
                            </>
                          );
                        })()}
                      </select>
                    </div>
                  )}
                </div>
              )}

              {courtLevel === 'district' && (
                <div className="mt-6 p-6 border rounded-xl bg-surface-container-lowest animate-fade-slide-up space-y-4">
                  <div>
                    <h3 className="font-bold text-on-surface mb-2">Select State</h3>
                    <select 
                      value={selectedState}
                      onChange={(e) => {
                        setSelectedState(e.target.value);
                        setSelectedDistrictCourt('');
                      }}
                      className="w-full p-3 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm bg-white"
                    >
                      <option value="" disabled>Choose a State...</option>
                      {indianStates.map((state) => (
                        <option key={state} value={state}>{state}</option>
                      ))}
                    </select>
                  </div>
                  
                  {selectedState && (
                    <div className="animate-fade-slide-up">
                      <h3 className="font-bold text-on-surface mb-2">Select District Court</h3>
                      <select 
                        value={selectedDistrictCourt}
                        onChange={(e) => setSelectedDistrictCourt(e.target.value)}
                        className="w-full p-3 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm bg-white"
                      >
                        <option value="" disabled>Choose a District Court...</option>
                        {getDistrictCourtsForState(selectedState).map((court) => (
                          <option key={court} value={court}>{court}</option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>
              )}

              {courtLevel === 'tribunal' && (
                <div className="mt-6 p-6 border rounded-xl bg-surface-container-lowest animate-fade-slide-up space-y-6">
                  <div>
                    <h3 className="font-bold text-on-surface mb-3">Choose Category</h3>
                    <div className="flex gap-4">
                      {[
                        { id: 'tribunal', label: 'Major Tribunal' },
                        { id: 'special_court', label: 'Special Court' }
                      ].map((sub) => (
                        <label key={sub.id} className={`flex-1 flex items-center justify-between p-4 border rounded-lg cursor-pointer transition-all duration-200 ${selectedSubLevel === sub.id ? 'border-primary bg-primary/5 shadow-[0_0_0_2px_rgba(14,107,82,0.1)]' : 'border-outline-variant bg-white hover:border-primary/50'}`} onClick={() => {
                          setSelectedSubLevel(sub.id as 'tribunal' | 'special_court');
                          setSelectedTribunal('');
                          setSelectedSpecialCourt('');
                        }}>
                          <div className="flex items-center gap-3">
                            <input type="radio" name="sub_level" value={sub.id} checked={selectedSubLevel === sub.id} onChange={() => {}} className="w-4 h-4 text-primary border-outline-variant focus:ring-primary" />
                            <span className={`text-sm font-semibold ${selectedSubLevel === sub.id ? 'text-primary' : 'text-on-surface'}`}>{sub.label}</span>
                          </div>
                        </label>
                      ))}
                    </div>
                  </div>

                  {selectedSubLevel === 'tribunal' && (
                    <div className="space-y-4 animate-fade-slide-up">
                      <div>
                        <h3 className="font-bold text-on-surface mb-2">Select Tribunal</h3>
                        <select 
                          value={selectedTribunal}
                          onChange={(e) => setSelectedTribunal(e.target.value)}
                          className="w-full p-3 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm bg-white"
                        >
                          <option value="" disabled>Choose a Tribunal...</option>
                          {tribunalsData.map((t) => (
                            <option key={t.name} value={t.name}>{t.name}</option>
                          ))}
                        </select>
                      </div>

                      {selectedTribunal && (() => {
                        const trib = tribunalsData.find(t => t.name === selectedTribunal);
                        if (!trib) return null;
                        return (
                          <div className="p-4 bg-white rounded-lg border border-outline-variant text-xs space-y-2 animate-fade-slide-up">
                            <div>
                              <span className="font-bold text-on-surface block mb-0.5">Handles:</span>
                              <p className="text-on-surface-variant leading-relaxed">{trib.handles}</p>
                            </div>
                            <div>
                              <span className="font-bold text-on-surface block mb-0.5">Bench Locations:</span>
                              <p className="text-on-surface-variant leading-relaxed">{trib.benchLocations}</p>
                            </div>
                          </div>
                        );
                      })()}
                    </div>
                  )}

                  {selectedSubLevel === 'special_court' && (
                    <div className="space-y-4 animate-fade-slide-up">
                      <div>
                        <h3 className="font-bold text-on-surface mb-2">Select Special Court</h3>
                        <select 
                          value={selectedSpecialCourt}
                          onChange={(e) => setSelectedSpecialCourt(e.target.value)}
                          className="w-full p-3 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm bg-white"
                        >
                          <option value="" disabled>Choose a Special Court...</option>
                          {specialCourtsData.map((sc) => (
                            <option key={sc.name} value={sc.name}>{sc.name}</option>
                          ))}
                        </select>
                      </div>

                      {selectedSpecialCourt && (() => {
                        const sc = specialCourtsData.find(s => s.name === selectedSpecialCourt);
                        if (!sc) return null;
                        return (
                          <div className="p-4 bg-white rounded-lg border border-outline-variant text-xs space-y-2 animate-fade-slide-up">
                            <div>
                              <span className="font-bold text-on-surface block mb-0.5">Purpose:</span>
                              <p className="text-on-surface-variant leading-relaxed">{sc.purpose}</p>
                            </div>
                            <div>
                              <span className="font-bold text-on-surface block mb-0.5">Governing Law:</span>
                              <p className="text-on-surface-variant leading-relaxed font-mono">{sc.governingLaw}</p>
                            </div>
                          </div>
                        );
                      })()}
                    </div>
                  )}
                </div>
              )}
            </>
          )}

          {currentStep === 2 && (
            <>
              <div className="mb-8">
                <h2 className="font-display-lg text-2xl font-bold text-on-surface mb-1">Select Case Type</h2>
                <p className="text-primary text-sm font-semibold uppercase tracking-wider">{courtLevel === 'supreme' ? 'Supreme Court of India' : courtLevel === 'high' ? 'High Court' : courtLevel === 'district' ? 'District Court' : selectedSubLevel === 'special_court' ? 'Special Court' : 'Tribunal'}</p>
              </div>
              <div className="space-y-6">
                <div>
                  <h3 className="font-bold text-on-surface mb-2">Category</h3>
                  {isLoadingCategories ? (
                    <div className="h-12 bg-surface-container-low border border-outline-variant/40 rounded-lg animate-pulse"></div>
                  ) : categoriesList.length === 0 ? (
                    <div className="text-center py-4 text-on-surface-variant text-sm border rounded-lg">No categories available.</div>
                  ) : (
                    <select 
                      className="w-full p-4 rounded-xl border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none bg-white text-on-surface shadow-sm"
                      value={selectedCategory ? selectedCategory.id : ""}
                      onChange={(e) => {
                        const cat = categoriesList.find(c => c.id.toString() === e.target.value);
                        setSelectedCategory(cat || null);
                        setSelectedCaseType(null);
                        setSelectedSubCategory(null);
                        setDocumentType(cat ? cat.name : ''); 
                      }}
                    >
                      <option value="" disabled>Select a Category...</option>
                      {categoriesList.map(cat => (
                        <option key={cat.id} value={cat.id}>{cat.name} {cat.summary ? `- ${cat.summary}` : ''}</option>
                      ))}
                    </select>
                  )}
                </div>

                {selectedCategory && (
                  <div className="animate-fade-slide-up">
                    <h3 className="font-bold text-on-surface mb-2">Subject</h3>
                    {isLoadingCaseTypes ? (
                      <div className="h-12 bg-surface-container-low border border-outline-variant/40 rounded-lg animate-pulse"></div>
                    ) : caseTypesList.length === 0 ? (
                      <div className="text-center py-4 text-on-surface-variant text-sm border rounded-lg">Proceed to next step.</div>
                    ) : (
                      <select 
                        className="w-full p-4 rounded-xl border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none bg-white text-on-surface shadow-sm"
                        value={selectedCaseType ? selectedCaseType.id : ""}
                        onChange={(e) => {
                          const ct = caseTypesList.find(c => c.id.toString() === e.target.value);
                          setSelectedCaseType(ct || null);
                          setSelectedSubCategory(null);
                          setSubjectMatter(ct ? ct.name : ''); 
                        }}
                      >
                        <option value="" disabled>Select a Subject...</option>
                        {caseTypesList.map(ct => (
                          <option key={ct.id} value={ct.id}>{ct.name}</option>
                        ))}
                      </select>
                    )}
                  </div>
                )}
              </div>
            </>
          )}

          {currentStep === 3 && (
            <>
              <div className="mb-8">
                <h2 className="font-display-lg text-2xl font-bold text-on-surface mb-1">Subject Matter</h2>
                <p className="text-sm text-on-surface-variant mb-4">Select the specific issue that best describes your case</p>
              </div>
              
              {(!categoriesList.length || (selectedCategory && selectedCategory.id >= 1000)) ? (
                <div className="space-y-6 animate-fade-slide-up">
                  <div>
                    <label className="block text-sm font-bold text-on-surface mb-1">Subject / Title</label>
                    {subjectMattersList.length > 0 ? (
                      <select 
                        value={subjectMatter}
                        onChange={(e) => setSubjectMatter(e.target.value)}
                        className="w-full p-4 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm transition-all text-on-surface bg-white"
                      >
                        <option value="" disabled>Select a Subject Matter...</option>
                        {subjectMattersList
                          .filter(sm => !documentType || !sm.applicable_doc_types || sm.applicable_doc_types.length === 0 || sm.applicable_doc_types.some((dt: string) => documentType.includes(dt) || dt.includes(documentType)))
                          .map(sm => (
                          <option key={sm.matter_name} value={sm.matter_name}>{sm.matter_name}</option>
                        ))}
                      </select>
                    ) : (
                      <input 
                        type="text" 
                        value={subjectMatter}
                        onChange={(e) => setSubjectMatter(e.target.value)}
                        placeholder="e.g. Challenging arbitrary termination..."
                        className="w-full p-4 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm transition-all text-on-surface"
                      />
                    )}
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-on-surface mb-1">Subject Matter Description</label>
                    <textarea 
                      value={caseDescription}
                      onChange={(e) => setCaseDescription(e.target.value)}
                      placeholder="e.g. Brief description of the case facts..."
                      className="w-full p-4 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm transition-all min-h-[120px] text-on-surface"
                    />
                  </div>
                </div>
              ) : (
                <div className="space-y-4">
                  {isLoadingSubCategories ? (
                    <div className="space-y-3 animate-pulse">
                      {[1, 2, 3].map((n) => (
                        <div key={n} className="h-14 bg-surface-container-low border border-outline-variant/40 rounded-lg"></div>
                      ))}
                    </div>
                  ) : subCategoriesList.length === 0 ? (
                    <div className="text-center py-6 text-on-surface-variant text-sm bg-surface-container-low rounded-lg border border-outline-variant">
                      No specific subcategories available for this subject. You can proceed.
                    </div>
                  ) : (
                    <select
                      value={selectedSubCategory ? selectedSubCategory.id : ""}
                      onChange={(e) => {
                        const sub = subCategoriesList.find(s => s.id.toString() === e.target.value);
                        if (sub) {
                          setSelectedSubCategory(sub);
                          setSubjectMatter(`${selectedCaseType?.name} — ${sub.name}`); 
                        }
                      }}
                      className="w-full p-4 rounded-xl border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none bg-white text-on-surface shadow-sm"
                    >
                      <option value="" disabled>Select a Specific Issue...</option>
                      {subCategoriesList.map((sub) => (
                        <option key={sub.id} value={sub.id}>{sub.name}</option>
                      ))}
                    </select>
                  )}
                  
                  <div className="mt-6 animate-fade-slide-up">
                    <label className="block text-sm font-bold text-on-surface mb-1">Subject Matter Description <span className="text-on-surface-variant font-normal">(Optional)</span></label>
                    <textarea 
                      value={caseDescription}
                      onChange={(e) => setCaseDescription(e.target.value)}
                      placeholder="e.g. Brief description of the case facts..."
                      className="w-full p-4 rounded-xl border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm transition-all min-h-[120px] text-on-surface shadow-sm bg-white"
                    />
                  </div>
                </div>
              )}
            </>
          )}

          {currentStep === 4 && (
            <>
              <div className="mb-6">
                <h2 className="font-display-lg text-2xl font-bold text-on-surface mb-1">Document Checklist</h2>
                <p className="text-on-surface-variant text-sm">For <span className="font-bold text-on-surface">{subjectMatter || 'Selected Matter'}</span> — provide the documents you have ready</p>
              </div>

              <div className="flex justify-between items-center text-sm font-bold text-on-surface border-b border-outline-variant pb-2 mb-6">
                <span>Documents confirmed</span>
                <span>{confirmedDocs} / {totalDocs}</span>
              </div>

              <div className="space-y-8">
                {isLoadingDocs ? (
                  <div className="space-y-4">
                    <div className="animate-pulse bg-surface-container-low h-[100px] rounded-xl border border-outline-variant"></div>
                    <div className="animate-pulse bg-surface-container-low h-[100px] rounded-xl border border-outline-variant"></div>
                    <div className="animate-pulse bg-surface-container-low h-[100px] rounded-xl border border-outline-variant"></div>
                  </div>
                ) : (
                  <>
                    {/* Required Documents */}
                    {requiredDocsList.length > 0 && (
                      <div>
                        <div className="flex items-center gap-3 mb-4">
                          <span className="bg-error/10 text-error px-2 py-1 rounded text-xs font-bold tracking-wider">REQUIRED</span>
                          <span className="text-sm text-on-surface-variant">Must have before filing</span>
                        </div>
                        <div className="space-y-4">
                          {requiredDocsList.map(doc => (
                            <div key={doc.document_name} className={`p-4 border rounded-xl flex flex-col sm:flex-row sm:items-center justify-between gap-4 transition-all ${uploadedDocs[doc.document_name] === 'uploaded' ? 'border-primary bg-primary/5' : uploadedDocs[doc.document_name] === 'unavailable' ? 'border-outline-variant bg-surface-container-low opacity-75' : 'border-outline-variant bg-white'}`}>
                              <div>
                                <div className="flex items-center gap-2 mb-1">
                                  {uploadedDocs[doc.document_name] === 'uploaded' && <span className="material-symbols-outlined text-primary text-sm font-bold">check_circle</span>}
                                  <h4 className={`font-bold ${uploadedDocs[doc.document_name] === 'uploaded' ? 'text-primary' : 'text-on-surface'}`}>{doc.document_name}</h4>
                                </div>
                                <p className="text-xs text-on-surface-variant">{doc.description}</p>
                              </div>
                              <div className="flex items-center gap-2">
                                <button 
                                  onClick={() => setDocStatus(doc.document_name, 'unavailable')}
                                  className={`px-3 py-1.5 text-xs font-semibold rounded-lg border transition-colors ${uploadedDocs[doc.document_name] === 'unavailable' ? 'bg-surface-container-highest border-outline text-on-surface' : 'bg-white border-outline-variant text-on-surface-variant hover:bg-surface-container-low'}`}
                                >
                                  Not Available
                                </button>
                                <label className={`cursor-pointer px-4 py-1.5 text-xs font-bold rounded-lg border transition-colors flex items-center gap-2 ${uploadedDocs[doc.document_name] === 'uploaded' ? 'bg-primary border-primary text-white' : 'bg-surface border-outline-variant text-primary hover:bg-primary/5 hover:border-primary/50'}`}>
                                  <span className="material-symbols-outlined text-[16px]">upload</span>
                                  {uploadedDocs[doc.document_name] === 'uploaded' ? 'Uploaded' : uploadedDocs[doc.document_name] === 'uploading' ? 'Uploading...' : 'Upload'}
                                  <input type="file" className="hidden" onChange={(e) => handleFileUpload(e, doc.document_name)} />
                                </label>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Optional Documents */}
                    {optionalDocsList.length > 0 && (
                      <div>
                        <div className="flex items-center gap-3 mb-4">
                          <span className="bg-[#E4C853]/20 text-[#715000] px-2 py-1 rounded text-xs font-bold tracking-wider">OPTIONAL</span>
                          <span className="text-sm text-on-surface-variant">Strengthens your case</span>
                        </div>
                        <div className="space-y-4">
                          {optionalDocsList.map(doc => (
                            <div key={doc.document_name} className={`p-4 border rounded-xl flex flex-col sm:flex-row sm:items-center justify-between gap-4 transition-all ${uploadedDocs[doc.document_name] === 'uploaded' ? 'border-primary bg-primary/5' : uploadedDocs[doc.document_name] === 'unavailable' ? 'border-outline-variant bg-surface-container-low opacity-75' : 'border-outline-variant bg-white'}`}>
                              <div>
                                <div className="flex items-center gap-2 mb-1">
                                  {uploadedDocs[doc.document_name] === 'uploaded' && <span className="material-symbols-outlined text-primary text-sm font-bold">check_circle</span>}
                                  <h4 className={`font-bold ${uploadedDocs[doc.document_name] === 'uploaded' ? 'text-primary' : 'text-on-surface'}`}>{doc.document_name}</h4>
                                </div>
                                <p className="text-xs text-on-surface-variant">{doc.description}</p>
                              </div>
                              <div className="flex items-center gap-2">
                                <button 
                                  onClick={() => setDocStatus(doc.document_name, 'unavailable')}
                                  className={`px-3 py-1.5 text-xs font-semibold rounded-lg border transition-colors ${uploadedDocs[doc.document_name] === 'unavailable' ? 'bg-surface-container-highest border-outline text-on-surface' : 'bg-white border-outline-variant text-on-surface-variant hover:bg-surface-container-low'}`}
                                >
                                  Not Available
                                </button>
                                <label className={`cursor-pointer px-4 py-1.5 text-xs font-bold rounded-lg border transition-colors flex items-center gap-2 ${uploadedDocs[doc.document_name] === 'uploaded' ? 'bg-primary border-primary text-white' : 'bg-surface border-outline-variant text-primary hover:bg-primary/5 hover:border-primary/50'}`}>
                                  <span className="material-symbols-outlined text-[16px]">upload</span>
                                  {uploadedDocs[doc.document_name] === 'uploaded' ? 'Uploaded' : uploadedDocs[doc.document_name] === 'uploading' ? 'Uploading...' : 'Upload'}
                                  <input type="file" className="hidden" onChange={(e) => handleFileUpload(e, doc.document_name)} />
                                </label>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            </>
          )}

          {currentStep === 5 && (
            <>
              <div className="mb-8">
                <h2 className="font-display-lg text-2xl font-bold text-on-surface mb-1">Parties & Facts</h2>
              </div>
              
              <div className="space-y-6">
                {/* Advocate Details */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 bg-surface-container-lowest p-4 rounded-xl border border-outline-variant">
                  <div className="col-span-full">
                    <h3 className="font-bold text-sm text-on-surface mb-1 flex items-center gap-2">
                      <span className="material-symbols-outlined text-sm">gavel</span>
                      Advocate Details *
                    </h3>
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-on-surface-variant mb-1">Name</label>
                    <input type="text" value={advocateName} onChange={(e) => setAdvocateName(e.target.value)} placeholder="Advocate on Record" className="w-full p-3 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm transition-all bg-white" />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-on-surface-variant mb-1">Enrollment Number</label>
                    <input type="text" value={advocateEnrollmentNo} onChange={(e) => setAdvocateEnrollmentNo(e.target.value)} placeholder="e.g. D/1234/2023" className="w-full p-3 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm transition-all bg-white" />
                  </div>
                </div>

                {/* Petitioners */}
                <div>
                  <label className="block text-sm font-bold text-on-surface mb-2">Petitioner / Appellant / Complainant *</label>
                  <div className="space-y-3">
                    {petitioners.map((pet, index) => (
                      <div key={`pet-${index}`} className="flex gap-2">
                        <input type="text" value={pet} onChange={(e) => updatePetitioner(index, e.target.value)} placeholder="Full name, s/o, d/o, R/o..." className="w-full p-3 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm transition-all" />
                        {petitioners.length > 1 && (
                          <button onClick={() => removePetitioner(index)} className="p-3 text-error hover:bg-error/10 rounded-lg transition-colors border border-transparent shrink-0">
                            <span className="material-symbols-outlined text-sm">delete</span>
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                  <button onClick={addPetitioner} className="mt-3 flex items-center gap-2 text-sm font-bold text-primary hover:text-[#004131] transition-colors">
                    <span className="material-symbols-outlined text-sm">add_circle</span> Add Another Petitioner
                  </button>
                </div>
                
                {/* Respondents */}
                <div>
                  <label className="block text-sm font-bold text-on-surface mb-2">Respondent / Opposite Party *</label>
                  <div className="space-y-3">
                    {respondents.map((res, index) => (
                      <div key={`res-${index}`} className="flex gap-2">
                        <input type="text" value={res} onChange={(e) => updateRespondent(index, e.target.value)} placeholder="Full name or designation..." className="w-full p-3 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm transition-all" />
                        {respondents.length > 1 && (
                          <button onClick={() => removeRespondent(index)} className="p-3 text-error hover:bg-error/10 rounded-lg transition-colors border border-transparent shrink-0">
                            <span className="material-symbols-outlined text-sm">delete</span>
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                  <button onClick={addRespondent} className="mt-3 flex items-center gap-2 text-sm font-bold text-primary hover:text-[#004131] transition-colors">
                    <span className="material-symbols-outlined text-sm">add_circle</span> Add Another Respondent
                  </button>
                </div>
                
                {/* New Case Details */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div>
                    <label className="block text-sm font-bold text-on-surface mb-1">Impugned Order Date</label>
                    <p className="text-xs text-on-surface-variant mb-2">Required for calculating limitation period</p>
                    <input type="date" value={impugnedOrderDate} onChange={(e) => setImpugnedOrderDate(e.target.value)} className="w-full p-3 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm transition-all text-on-surface bg-white" />
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-on-surface mb-1">Jurisdiction Basis</label>
                    <p className="text-xs text-on-surface-variant mb-2">Why this court has jurisdiction</p>
                    <input type="text" value={jurisdictionBasis} onChange={(e) => setJurisdictionBasis(e.target.value)} placeholder="e.g. Cause of action arose in Delhi" className="w-full p-3 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm transition-all bg-white" />
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-bold text-on-surface mb-1">Facts of the Case</label>
                  <p className="text-xs text-on-surface-variant mb-2">Chronological facts with dates. Leave blank and AI will draft based on your description.</p>
                  <textarea value={factsOfCase} onChange={(e) => setFactsOfCase(e.target.value)} placeholder="1. That the petitioner is the recorded owner of... 2. That on [date], the respondent..." className="w-full p-4 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm transition-all min-h-[100px]" />
                </div>

                <div>
                  <label className="block text-sm font-bold text-on-surface mb-1">Grounds</label>
                  <p className="text-xs text-on-surface-variant mb-2">Legal grounds to be raised. Leave blank and AI will draft appropriate grounds.</p>
                  <textarea value={grounds} onChange={(e) => setGrounds(e.target.value)} placeholder="A. That the impugned order is without jurisdiction... B. That the respondent has violated..." className="w-full p-4 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm transition-all min-h-[100px]" />
                </div>

                <div>
                  <label className="block text-sm font-bold text-on-surface mb-1">Relief Sought</label>
                  <p className="text-xs text-on-surface-variant mb-2">What you want the court to order. Leave blank for AI to draft.</p>
                  <textarea value={reliefSought} onChange={(e) => setReliefSought(e.target.value)} placeholder="i. Issue a writ of mandamus directing... ii. Stay the operation of..." className="w-full p-4 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm transition-all min-h-[80px]" />
                </div>

                <div>
                  <label className="block text-sm font-bold text-on-surface mb-1">Interim Relief Sought (Optional)</label>
                  <p className="text-xs text-on-surface-variant mb-2">Urgent relief like stay orders, status quo.</p>
                  <textarea value={interimReliefSought} onChange={(e) => setInterimReliefSought(e.target.value)} placeholder="e.g. Stay the operation of the impugned order dated..." className="w-full p-4 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm transition-all min-h-[80px]" />
                </div>

                <div className="bg-surface-container-lowest p-5 rounded-xl border border-outline-variant">
                  <h3 className="font-bold text-sm text-on-surface mb-3 flex items-center gap-2">
                    <span className="material-symbols-outlined text-primary text-base">verified_user</span>
                    Verification Statement Preview
                  </h3>
                  <div className="border-l-4 border-primary/30 pl-4 py-2">
                    <p className="text-sm text-on-surface-variant italic leading-relaxed">
                      "I, <span className="font-semibold text-on-surface not-italic">{petitioners[0] || '[Petitioner Name]'}</span>, the petitioner herein, do hereby verify that the contents of the above paragraphs are true and correct to my knowledge and belief and nothing material has been concealed therefrom."
                    </p>
                  </div>
                </div>
              </div>

              <div className="mt-8 bg-surface-container-low p-6 rounded-xl border border-outline-variant">
                <h4 className="font-bold text-sm tracking-wider uppercase mb-4 text-on-surface">Draft Summary</h4>
                <div className="grid grid-cols-[150px_1fr] gap-y-2 text-sm">
                  <span className="text-on-surface-variant">Court:</span>
                  <span className="font-medium text-on-surface capitalize">
                    {courtLevel === 'high' && selectedHighCourt ? `${selectedHighCourt}${selectedHighCourtBench ? ` - ${selectedHighCourtBench}` : ''}` : 
                     courtLevel === 'district' && selectedDistrictCourt ? `${selectedDistrictCourt}, ${selectedState}` : 
                     courtLevel === 'tribunal' && selectedSubLevel === 'tribunal' && selectedTribunal ? selectedTribunal :
                     courtLevel === 'tribunal' && selectedSubLevel === 'special_court' && selectedSpecialCourt ? selectedSpecialCourt :
                     `${courtLevel} Court`}
                  </span>
                  <span className="text-on-surface-variant">Case Type:</span>
                  <span className="font-medium text-on-surface">{documentType || 'Not selected'}</span>
                  <span className="text-on-surface-variant">Subject:</span>
                  <span className="font-medium text-on-surface">{subjectMatter || 'Not selected'}</span>
                  <span className="text-on-surface-variant">Documents confirmed:</span>
                  <span className="font-medium text-on-surface">{confirmedDocs}</span>
                </div>
              </div>
            </>
          )}

          {currentStep === 6 && (
            <>
              <div className="mb-6">
                <h2 className="font-display-lg text-2xl font-bold text-on-surface mb-1">Select Citations</h2>
                <p className="text-on-surface-variant text-sm">Review and select the legal precedents and statutes you want to cite in your draft.</p>
              </div>

              {isLoadingCitations ? (
                <div className="flex flex-col items-center justify-center py-12">
                  <div className="w-12 h-12 border-4 border-primary/20 border-t-primary rounded-full animate-spin mb-4"></div>
                  <p className="font-bold text-on-surface">Searching for Relevant Case Laws...</p>
                  <p className="text-sm text-on-surface-variant mt-2">Analyzing facts and extracting relevant sections.</p>
                </div>
              ) : (
                <div className="space-y-8">
                  {/* Statutes Section */}
                  <div>
                    <h3 className="font-bold text-on-surface mb-4 flex items-center gap-2">
                      <span className="material-symbols-outlined text-primary">local_library</span>
                      Relevant Statutes & Codes
                    </h3>
                    
                    {suggestedStatutes.length === 0 ? (
                      <p className="text-sm text-on-surface-variant italic">No relevant statutes found for this case.</p>
                    ) : (
                      <div className="space-y-3">
                        {suggestedStatutes.map((statute) => (
                          <label key={statute.id} className={`flex items-start gap-4 p-4 border rounded-xl cursor-pointer transition-all ${selectedStatuteIds.has(statute.id) ? 'border-primary bg-primary/5' : 'border-outline-variant hover:border-primary/30'}`}>
                            <input 
                              type="checkbox" 
                              className="mt-1 w-4 h-4 text-primary rounded border-outline focus:ring-primary"
                              checked={selectedStatuteIds.has(statute.id)}
                              onChange={(e) => {
                                const newSet = new Set(selectedStatuteIds);
                                if (e.target.checked) newSet.add(statute.id);
                                else newSet.delete(statute.id);
                                setSelectedStatuteIds(newSet);
                              }}
                            />
                            <div>
                              <h4 className="font-bold text-on-surface">{statute.title}</h4>
                              <p className="text-xs text-on-surface-variant mt-1 line-clamp-2">{statute.text}</p>
                            </div>
                          </label>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Judgments Section */}
                  <div>
                    <h3 className="font-bold text-on-surface mb-4 flex items-center gap-2">
                      <span className="material-symbols-outlined text-primary">gavel</span>
                      Precedents & Case Laws
                    </h3>
                    
                    {suggestedJudgments.length === 0 ? (
                      <p className="text-sm text-on-surface-variant italic">No relevant precedents found for this case.</p>
                    ) : (
                      <div className="space-y-3">
                        {suggestedJudgments.map((judgment) => (
                          <label key={judgment.id} className={`flex items-start gap-4 p-4 border rounded-xl cursor-pointer transition-all ${selectedJudgmentIds.has(judgment.id) ? 'border-primary bg-primary/5' : 'border-outline-variant hover:border-primary/30'}`}>
                            <input 
                              type="checkbox" 
                              className="mt-1 w-4 h-4 text-primary rounded border-outline focus:ring-primary"
                              checked={selectedJudgmentIds.has(judgment.id)}
                              onChange={(e) => {
                                const newSet = new Set(selectedJudgmentIds);
                                if (e.target.checked) newSet.add(judgment.id);
                                else newSet.delete(judgment.id);
                                setSelectedJudgmentIds(newSet);
                              }}
                            />
                            <div>
                              <div className="flex items-center gap-2 flex-wrap">
                                <h4 className="font-bold text-on-surface">{judgment.title}</h4>
                                {judgment.case_number && (
                                  <span className="text-xs bg-surface-container-high px-2 py-0.5 rounded font-mono">{judgment.case_number}</span>
                                )}
                                {judgment.year && (
                                  <span className="text-xs text-on-surface-variant">({judgment.year})</span>
                                )}
                              </div>
                              <p className="text-xs text-on-surface-variant mt-1 line-clamp-3">{judgment.text}</p>
                            </div>
                          </label>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </>
          )}

          {currentStep === 7 && generateStatus === 'loading' && (
            <div className="text-center py-20 flex-1 flex flex-col items-center justify-center">
              <div className="w-20 h-20 bg-primary/10 rounded-full flex items-center justify-center mx-auto mb-6">
                <span className="material-symbols-outlined text-primary text-4xl animate-pulse">magic_button</span>
              </div>
              <h2 className="font-display-lg text-3xl font-bold mb-4">Generating Your Draft...</h2>
              <p className="text-on-surface-variant max-w-md mx-auto mb-8">
                Writon AI is analyzing your {confirmedDocs} provided documents, aligning with {courtLevel} Court formats, and researching relevant SC precedents for your {subjectMatter} case.
              </p>
              
              <div className="max-w-xs mx-auto space-y-4 w-full">
                <div className="h-2 bg-surface-container-highest rounded-full overflow-hidden">
                  <div className="h-full bg-primary w-2/3 rounded-full animate-[pulse_1.5s_ease-in-out_infinite]"></div>
                </div>
                <p className="text-sm font-semibold text-primary">Formulating Legal Structure...</p>
              </div>
            </div>
          )}

          {currentStep === 7 && (generateStatus === 'streaming' || generateStatus === 'completed') && (
            <div className="flex-1 flex flex-col h-full bg-surface-container-lowest animate-fade-slide-up">
              {/* Toolbar */}
              <div className="flex items-center justify-between p-4 border-b border-outline-variant bg-white print:hidden">
                <div className="flex items-center gap-2">
                  <button onMouseDown={(e) => e.preventDefault()} onClick={() => handleFormat('bold')} className="w-8 h-8 flex items-center justify-center rounded hover:bg-surface-container-low text-on-surface transition-colors" title="Bold">
                    <span className="material-symbols-outlined text-lg">format_bold</span>
                  </button>
                  <button onMouseDown={(e) => e.preventDefault()} onClick={() => handleFormat('italic')} className="w-8 h-8 flex items-center justify-center rounded hover:bg-surface-container-low text-on-surface transition-colors" title="Italic">
                    <span className="material-symbols-outlined text-lg">format_italic</span>
                  </button>
                  <button onMouseDown={(e) => e.preventDefault()} onClick={() => handleFormat('underline')} className="w-8 h-8 flex items-center justify-center rounded hover:bg-surface-container-low text-on-surface transition-colors" title="Underline">
                    <span className="material-symbols-outlined text-lg">format_underlined</span>
                  </button>
                  <div className="w-px h-6 bg-outline-variant mx-1"></div>
                  <button onMouseDown={(e) => e.preventDefault()} onClick={() => handleFormat('justifyLeft')} className="w-8 h-8 flex items-center justify-center rounded hover:bg-surface-container-low text-on-surface transition-colors">
                    <span className="material-symbols-outlined text-lg">format_align_left</span>
                  </button>
                  <button onMouseDown={(e) => e.preventDefault()} onClick={() => handleFormat('justifyCenter')} className="w-8 h-8 flex items-center justify-center rounded hover:bg-surface-container-low text-on-surface transition-colors">
                    <span className="material-symbols-outlined text-lg">format_align_center</span>
                  </button>
                  <button onMouseDown={(e) => e.preventDefault()} onClick={() => handleFormat('justifyFull')} className="w-8 h-8 flex items-center justify-center rounded hover:bg-surface-container-low text-on-surface transition-colors">
                    <span className="material-symbols-outlined text-lg">format_align_justify</span>
                  </button>
                </div>
                
                <div className="flex items-center gap-3">
                  <span className={`text-xs font-bold px-3 py-1 rounded-full ${generateStatus === 'completed' ? 'bg-[#004131]/10 text-[#004131]' : 'bg-primary text-white animate-pulse'}`}>
                    {generateStatusText}
                  </span>
                  <button onClick={() => {
                      if (!isEditingMode && !hasEdited) {
                          setHtmlPages(pageRefs.current.map(r => r?.innerHTML || ''));
                          setHasEdited(true);
                      }
                      setIsEditingMode(!isEditingMode);
                  }} className={`flex items-center gap-2 px-3 py-1.5 text-sm font-bold rounded transition-colors ${isEditingMode ? 'bg-primary text-white' : 'bg-surface-container-low text-on-surface hover:bg-surface-container'}`}>
                    <span className="material-symbols-outlined text-[16px]">{isEditingMode ? 'visibility' : 'edit'}</span>
                    {isEditingMode ? 'Preview Mode' : 'Edit Text'}
                  </button>
                  <button onClick={handleDownloadWord} className="flex items-center gap-2 px-4 py-1.5 bg-[#2b579a] text-white text-sm font-bold rounded hover:bg-[#1a3a6c] transition-colors">
                    <span className="material-symbols-outlined text-[16px]">description</span>
                    Word
                  </button>
                  <button onClick={handleDownloadPDF} className="flex items-center gap-2 px-4 py-1.5 bg-primary text-white text-sm font-bold rounded hover:bg-[#004131] transition-colors">
                    <span className="material-symbols-outlined text-[16px]">download</span>
                    PDF
                  </button>
                </div>
              </div>

              {/* Editor Workspace */}
              <div className="flex-1 overflow-y-auto bg-surface-container-highest p-8 md:p-12 print:p-0 print:bg-white print:overflow-visible print:block">
                
                {/* Dynamically Inject Print Styling to Override Inline Padding & Configure Page Margins */}
                <style type="text/css" media="print">
                  {`
                    @page {
                      size: A4;
                      margin-top: 1in;
                      margin-bottom: 0.5in;
                      margin-right: 1in;
                      margin-left: ${courtLevel === 'supreme' ? '2in' : courtLevel === 'high' ? '1.5in' : '1in'};
                    }
                    .html2pdf__page-break {
                      padding: 0 !important;
                      margin: 0 !important;
                      box-shadow: none !important;
                      border: none !important;
                      background: transparent !important;
                      min-height: 0 !important;
                      height: auto !important;
                    }
                    .print-table { display: table !important; }
                    .print-tfoot { display: table-footer-group !important; }
                    .print-tbody { display: table-row-group !important; }
                    .print-td { display: table-cell !important; }
                  `}
                </style>

                <table className="w-full block print-table">
                  <tfoot className="hidden print-tfoot">
                    <tr>
                      <td className="border-none pt-4 pb-2">
                        <table style={{ width: '100%', border: 'none', fontFamily: '"Times New Roman", Times, serif', fontSize: '12pt' }}>
                          <tbody>
                            <tr>
                              <td style={{ width: '50%', verticalAlign: 'bottom', border: 'none' }}>
                                PLACE: ______________<br/>
                                DATED: ______________
                              </td>
                              <td style={{ width: '50%', textAlign: 'right', verticalAlign: 'bottom', border: 'none' }}>
                                <b>({(advocateName || "____________________").toUpperCase()})</b><br/>
                                Advocate<br/>
                                Enrollment No. {advocateEnrollmentNo || "_______________"}<br/>
                                Counsel for Petitioner
                              </td>
                            </tr>
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  </tfoot>
                  <tbody className="block print-tbody">
                    <tr>
                      <td className="block print-td border-none p-0">
                        <div ref={editorRef} className="print:bg-white">
                          {draftContent.split(/<<SECTION:\w+>>|<<END_SECTION>>/).map(content => content.trim()).filter(content => content.length > 0).map((pageContent, index) => (
                            <div 
                              key={index}
                              className="html2pdf__page-break max-w-[850px] mx-auto bg-white shadow-xl min-h-[1123px] border border-outline-variant mb-8 print:shadow-none print:border-none print:m-0 print:max-w-none print:break-after-page"
                              style={{ 
                                boxShadow: '0 10px 25px rgba(0,0,0,0.05), 0 0 1px rgba(0,0,0,0.1)',
                                paddingTop: '1in',
                                paddingRight: '1in',
                                paddingBottom: '1in',
                                paddingLeft: courtLevel === 'supreme' ? '2in' : courtLevel === 'high' ? '1.5in' : '1in',
                                position: 'relative'
                              }}
                            >
                              {!isEditingMode && !hasEdited ? (
                                <div 
                                  ref={el => { pageRefs.current[index] = el; }}
                                  className="text-on-surface outline-none prose prose-slate max-w-none"
                                  style={{ 
                                    fontFamily: '"Times New Roman", Times, serif', 
                                    fontSize: '12pt',
                                    lineHeight: '1.5'
                                  }}
                                >
                                  <ReactMarkdown 
                                    remarkPlugins={[remarkGfm]}
                                    rehypePlugins={[rehypeRaw]}
                                    components={{
                                      hr: ({...props}) => <hr className="border-0 border-b border-dashed border-outline-variant w-full print:border-transparent print:m-0" style={{ margin: '2rem 0' }} {...props} />,
                                      table: ({...props}) => <table className="w-full text-left border-collapse border border-outline-variant my-6" {...props} />,
                                      th: ({...props}) => <th className="border border-outline-variant px-4 py-2 bg-surface-container-low font-bold" {...props} />,
                                      td: ({...props}) => <td className="border border-outline-variant px-4 py-2" {...props} />,
                                      h1: ({...props}) => <h1 className="text-center font-bold uppercase mb-6" style={{ fontSize: '16pt', margin: '1.5rem 0 1rem 0', fontFamily: '"Times New Roman", Times, serif' }} {...props} />,
                                      h2: ({...props}) => <h2 className="text-center font-bold uppercase mt-8 mb-4" style={{ fontSize: '14pt', margin: '1.5rem 0 1rem 0', fontFamily: '"Times New Roman", Times, serif' }} {...props} />,
                                      h3: ({...props}) => <h3 className="font-bold uppercase mt-6 mb-3" style={{ fontSize: '14pt', margin: '1.2rem 0 0.6rem 0', fontFamily: '"Times New Roman", Times, serif' }} {...props} />,
                                      p: ({...props}) => <p className="whitespace-pre-wrap" style={{ marginBottom: '1rem', marginTop: 0, textAlign: 'justify', textJustify: 'inter-word', lineHeight: '1.5' }} {...props} />,
                                      ul: ({...props}) => <ul className="list-disc pl-6 my-3" style={{ margin: '0.5rem 0 0.5rem 1.5rem' }} {...props} />,
                                      ol: ({...props}) => <ol className="list-decimal pl-6 my-3" style={{ margin: '0.5rem 0 0.5rem 1.5rem' }} {...props} />,
                                      li: ({...props}) => <li style={{ margin: '0.3rem 0', lineHeight: '1.5', textAlign: 'justify' }} {...props} />
                                    }}
                                  >
                                    {pageContent}
                                  </ReactMarkdown>
                                </div>
                              ) : (
                                <div
                                  contentEditable={isEditingMode}
                                  className={`text-on-surface outline-none prose prose-slate max-w-none ${isEditingMode ? 'ring-2 ring-primary/20 rounded' : ''}`}
                                  style={{ 
                                    fontFamily: '"Times New Roman", Times, serif', 
                                    fontSize: '12pt',
                                    lineHeight: '1.5',
                                    minHeight: '100%'
                                  }}
                                  dangerouslySetInnerHTML={{ __html: hasEdited ? htmlPages[index] : (pageRefs.current[index]?.innerHTML || '') }}
                                  onInput={(e) => {
                                    if (!hasEdited) setHasEdited(true);
                                    const newHtml = [...(hasEdited ? htmlPages : pageRefs.current.map(r => r?.innerHTML || ''))];
                                    newHtml[index] = e.currentTarget.innerHTML;
                                    setHtmlPages(newHtml);
                                  }}
                                />
                              )}
                            </div>
                          ))}
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* Citation Verification Panel */}
              {citations.length > 0 && (
                <div className="border-t border-outline-variant bg-surface-container-lowest px-8 py-5 print:hidden">
                  <h4 className="font-bold text-sm tracking-wider uppercase mb-3 text-on-surface flex items-center gap-2">
                    <span className="material-symbols-outlined text-base text-primary">fact_check</span>
                    Citation Verification
                  </h4>
                  <div className="flex flex-wrap gap-2">
                    {citations.map((c, i) => (
                      <span key={i} title={c.status !== 'verified' ? 'Could not be verified in database — please confirm before filing' : 'Found in database'}
                        className={`inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full font-medium border cursor-default ${
                          c.status === 'verified'
                            ? 'bg-[#004131]/10 text-[#004131] border-[#004131]/20'
                            : 'bg-error/10 text-error border-error/20'
                        }`}>
                        <span className="material-symbols-outlined text-[14px]">
                          {c.status === 'verified' ? 'verified' : 'warning'}
                        </span>
                        {c.citation}
                        {c.status !== 'verified' && (
                          <span className="opacity-70 text-[10px] font-normal"> — confirm before filing</span>
                        )}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Sticky Bottom Action Bar (Hidden during editor view) */}
        {!(currentStep === 7 && generateStatus !== 'loading' && generateStatus !== 'idle') && (
          <div className="mt-8 flex justify-between items-center print:hidden">
            <button 
              onClick={handleBack}
              disabled={currentStep === 1}
              className={`flex items-center gap-2 px-6 py-2.5 rounded-lg border font-bold transition-all ${currentStep === 1 ? 'border-outline-variant/50 text-outline cursor-not-allowed bg-transparent' : 'border-outline-variant text-on-surface bg-white hover:bg-surface-container-low hover:shadow-sm'}`}>
              <span className="material-symbols-outlined text-sm">arrow_back</span>
              Back
            </button>
            
            {currentStep < 7 ? (
              <button 
                onClick={handleNext}
                disabled={
                  (currentStep === 1 && courtLevel === 'high' && (!selectedHighCourt || !selectedHighCourtBench)) ||
                  (currentStep === 1 && courtLevel === 'district' && (!selectedState || !selectedDistrictCourt)) ||
                  (currentStep === 1 && courtLevel === 'tribunal' && (
                    !selectedSubLevel ||
                    (selectedSubLevel === 'tribunal' && !selectedTribunal) ||
                    (selectedSubLevel === 'special_court' && !selectedSpecialCourt)
                  )) ||
                  (currentStep === 2 && !documentType) ||
                  (currentStep === 3 && !subjectMatter) ||
                  isLoadingDocs || isLoadingCitations
                }
                className="flex items-center gap-2 bg-primary text-white px-8 py-3 rounded-lg font-bold shadow-md hover:-translate-y-0.5 hover:shadow-lg hover:bg-[#004131] active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:translate-y-0 transition-all duration-300">
                {currentStep === 6 ? (
                  <>Generate Draft <span className="material-symbols-outlined text-[18px]">auto_awesome</span></>
                ) : (
                  <>Next <span className="material-symbols-outlined text-sm">arrow_forward</span></>
                )}
              </button>
            ) : (
              <div /> // Editor has its own controls
            )}
          </div>
        )}
      </main>
    </div>
  );
}
