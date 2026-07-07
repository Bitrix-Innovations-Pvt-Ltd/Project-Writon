'use client';

import { useState, useEffect, useRef } from 'react';
import Navbar from '@/components/shared/Navbar';
import Link from 'next/link';
import { useAuth } from '@clerk/nextjs';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';

import { districtCourtsData, tribunalsData, specialCourtsData } from './courtsData';

const indianStates = Object.keys(districtCourtsData).sort();

const highCourts = [
  "Allahabad High Court", "Andhra Pradesh High Court", "Bombay High Court", "Calcutta High Court", 
  "Chhattisgarh High Court", "Delhi High Court", "Gauhati High Court", "Gujarat High Court", 
  "Himachal Pradesh High Court", "Jammu & Kashmir and Ladakh High Court", "Jharkhand High Court", 
  "Karnataka High Court", "Kerala High Court", "Madhya Pradesh High Court", "Madras High Court", 
  "Manipur High Court", "Meghalaya High Court", "Orissa High Court", "Patna High Court", 
  "Punjab and Haryana High Court", "Rajasthan High Court", "Sikkim High Court", 
  "Telangana High Court", "Tripura High Court", "Uttarakhand High Court"
];

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
  const [uploadedDocs, setUploadedDocs] = useState<Record<string, string>>({}); 
  const [uploadError, setUploadError] = useState<string | null>(null); 
  
  // Step 5: Parties & Facts State
  const [advocateName, setAdvocateName] = useState('');
  const [advocateEnrollmentNo, setAdvocateEnrollmentNo] = useState('');
  const [petitioners, setPetitioners] = useState<string[]>(['']);
  const [respondents, setRespondents] = useState<string[]>(['']);
  const [impugnedOrderDate, setImpugnedOrderDate] = useState('');
  const [jurisdictionBasis, setJurisdictionBasis] = useState('');
  const [interimReliefSought, setInterimReliefSought] = useState('');

  const [selectedHighCourt, setSelectedHighCourt] = useState('');
  const [selectedState, setSelectedState] = useState('');
  const [selectedDistrictCourt, setSelectedDistrictCourt] = useState('');
  const [selectedSubLevel, setSelectedSubLevel] = useState<'tribunal' | 'special_court' | ''>('');
  const [selectedTribunal, setSelectedTribunal] = useState('');
  const [selectedSpecialCourt, setSelectedSpecialCourt] = useState('');
  const [documentTypes, setDocumentTypes] = useState<string[]>([]);
  const [isLoadingDocTypes, setIsLoadingDocTypes] = useState(false);
  const [subjectMattersList, setSubjectMattersList] = useState<{matter_name: string, applicable_doc_types: string[]}[]>([]);
  const [isLoadingSubjectMatters, setIsLoadingSubjectMatters] = useState(false);
  
  const [requiredDocsList, setRequiredDocsList] = useState<any[]>([]);
  const [optionalDocsList, setOptionalDocsList] = useState<any[]>([]);
  const [isLoadingDocs, setIsLoadingDocs] = useState(false);

  // Generation state
  const [generateStatus, setGenerateStatus] = useState<'idle' | 'loading' | 'streaming' | 'completed'>('idle');
  const [generateStatusText, setGenerateStatusText] = useState('Generating your draft...');
  const [draftContent, setDraftContent] = useState('');
  const [isEditingMode, setIsEditingMode] = useState(false);
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
      const res = await fetch("http://localhost:8000/api/v1/uploads", {
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

  // Reset selected subject matter if it's no longer in the fetched list
  useEffect(() => {
    if (subjectMattersList.length > 0 && !subjectMattersList.some(sm => sm.matter_name === subjectMatter)) {
      setSubjectMatter('');
    }
  }, [subjectMattersList]);

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
    { num: 6, label: 'Generate' },
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

    if (currentStep < 6) {
      setCurrentStep(currentStep + 1);
      if (currentStep + 1 === 6) {
        startGeneration();
      }
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
      courtLevel === 'high' && selectedHighCourt ? selectedHighCourt :
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
    };

    try {
      const response = await fetch('http://localhost:8000/api/v1/drafts/generate', {
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
    // Markdown formatting helper since we are now rendering markdown
    const selection = window.getSelection()?.toString();
    if (!selection) return;
    
    // We can't use execCommand on Markdown directly easily, 
    // but in a real app we'd update the draftContent string state.
    // For now, this is a visual stub for the markdown editor.
  };

  const handleDownloadPDF = async () => {
    if (!editorRef.current) return;
    
    // Dynamically import html2pdf to avoid SSR issues
    const html2pdf = (await import('html2pdf.js')).default;
    
    const element = editorRef.current;
    // CSS margins: [top, right, bottom, left]
    let pdfMargin = [1, 1, 1.75, 1];
    if (courtLevel === 'supreme') pdfMargin = [1, 1, 1.75, 2];
    else if (courtLevel === 'high') pdfMargin = [1, 1, 1.75, 1.5];

    const opt = {
      margin:       pdfMargin,
      filename:     `Draft_Petition_${new Date().toISOString().split('T')[0]}.pdf`,
      image:        { type: 'jpeg', quality: 0.98 },
      html2canvas:  { scale: 2, useCORS: true },
      jsPDF:        { unit: 'in', format: 'a4', orientation: 'portrait' },
      pagebreak:    { mode: ['css', 'legacy'] }
    };

    setGenerateStatusText('Generating PDF...');
    await html2pdf().from(element).set(opt).toPdf().get('pdf').then((pdf: any) => {
      const totalPages = pdf.internal.getNumberOfPages();
      for (let i = 1; i <= totalPages; i++) {
        pdf.setPage(i);
        
        // Page Number (Bottom Center)
        pdf.setFont("times", "normal");
        pdf.setFontSize(10);
        pdf.text(
          `Page ${i} of ${totalPages}`, 
          pdf.internal.pageSize.getWidth() / 2, 
          pdf.internal.pageSize.getHeight() - 0.5, 
          { align: 'center' }
        );

        // Left Footer
        pdf.text("PLACE: ______________", 1, pdf.internal.pageSize.getHeight() - 1.0);
        pdf.text("DATED: ______________", 1, pdf.internal.pageSize.getHeight() - 0.8);
        
        // Right Footer
        const rightX = pdf.internal.pageSize.getWidth() - (courtLevel === 'supreme' ? 1 : 1);
        const advName = advocateName || "____________________";
        const advEnroll = advocateEnrollmentNo || "_______________";
        
        pdf.setFont("times", "bold");
        pdf.text(`(${advName.toUpperCase()})`, rightX, pdf.internal.pageSize.getHeight() - 1.4, { align: 'right' });
        pdf.setFont("times", "normal");
        pdf.text("Advocate", rightX, pdf.internal.pageSize.getHeight() - 1.2, { align: 'right' });
        pdf.text(`Enrollment No. ${advEnroll}`, rightX, pdf.internal.pageSize.getHeight() - 1.0, { align: 'right' });
        pdf.text("Counsel for Petitioner", rightX, pdf.internal.pageSize.getHeight() - 0.8, { align: 'right' });
      }
    }).save();

    if (generateStatus === 'completed') {
      setGenerateStatusText('Generation Complete');
    }
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

      <main className={`flex-1 flex flex-col ${currentStep === 6 && generateStatus !== 'idle' && generateStatus !== 'loading' ? 'max-w-6xl w-full mx-auto px-4 py-8' : 'max-w-[900px] mx-auto py-12 px-4 md:px-0'}`}>
        
        {/* Hide header and stepper if we are in the editor view */}
        {!(currentStep === 6 && generateStatus !== 'loading' && generateStatus !== 'idle') && (
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
        <div className={`animate-fade-slide-up bg-white rounded-2xl shadow-sm border border-outline-variant ${currentStep === 6 && generateStatus !== 'loading' && generateStatus !== 'idle' ? 'flex-1 flex flex-col overflow-hidden' : 'p-8 md:p-10 space-y-6'}`}>
          
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
                <div className="mt-6 p-6 border rounded-xl bg-surface-container-lowest animate-fade-slide-up">
                  <h3 className="font-bold text-on-surface mb-2">Select High Court</h3>
                  <select 
                    value={selectedHighCourt}
                    onChange={(e) => setSelectedHighCourt(e.target.value)}
                    className="w-full p-3 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm bg-white"
                  >
                    <option value="" disabled>Choose a High Court...</option>
                    {highCourts.map((court) => (
                      <option key={court} value={court}>{court}</option>
                    ))}
                  </select>
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
                <h2 className="font-display-lg text-2xl font-bold text-on-surface mb-1">Select Document Type</h2>
                <p className="text-primary text-sm font-semibold uppercase tracking-wider">{courtLevel === 'supreme' ? 'Supreme Court of India' : courtLevel === 'high' ? 'High Court' : courtLevel === 'district' ? 'District Court' : selectedSubLevel === 'special_court' ? 'Special Court' : 'Tribunal'}</p>
              </div>
              <div className="space-y-3">
                {isLoadingDocTypes ? (
                  <div className="space-y-3 animate-pulse">
                    {[1, 2, 3, 4, 5].map((n) => (
                      <div key={n} className="h-14 bg-surface-container-low border border-outline-variant/40 rounded-lg"></div>
                    ))}
                  </div>
                ) : documentTypes.length === 0 ? (
                  <div className="text-center py-6 text-on-surface-variant text-sm">
                    No document types available. Please go back and make a selection.
                  </div>
                ) : (
                  documentTypes.map((type) => (
                    <label key={type} className={`block p-4 border rounded-lg cursor-pointer transition-all duration-200 hover:shadow-sm ${documentType === type ? 'border-primary bg-primary/5 shadow-[0_0_0_2px_rgba(14,107,82,0.1)]' : 'border-outline-variant bg-white hover:border-primary/50'}`}>
                      <div className="flex items-center gap-4">
                        <input type="radio" name="document_type" value={type} checked={documentType === type} onChange={() => setDocumentType(type)} className="w-5 h-5 text-primary border-outline-variant focus:ring-primary" />
                        <span className={`font-medium ${documentType === type ? 'text-primary' : 'text-on-surface'}`}>{type}</span>
                      </div>
                    </label>
                  ))
                )}
              </div>
            </>
          )}

          {currentStep === 3 && (
            <>
              <div className="mb-8">
                <h2 className="font-display-lg text-2xl font-bold text-on-surface mb-1">Subject Matter</h2>
              </div>
              
              <div className="mb-8">
                <h3 className="font-bold text-on-surface mb-1">Nature of Dispute</h3>
                <p className="text-sm text-on-surface-variant mb-4">Select the category that best describes your case — this determines which documents you need</p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {isLoadingSubjectMatters ? (
                    Array(6).fill(0).map((_, i) => (
                      <div key={i} className="animate-pulse flex p-3 border border-outline-variant rounded-lg bg-surface-container-low h-[46px]"></div>
                    ))
                  ) : subjectMattersList.length === 0 ? (
                    <div className="col-span-1 md:col-span-2 text-sm text-on-surface-variant p-4 bg-surface-container-low rounded-lg border border-outline-variant">
                      No subject matters available for this court combination.
                    </div>
                  ) : (
                    (() => {
                      const filteredMatters = subjectMattersList.filter((matter) => {
                        // Always allow "Other" to be selectable
                        if (matter.matter_name === 'Other') return true;
                        
                        // If no document type is selected, show all
                        if (!documentType) return true;
                        
                        // If a document type is selected, only show subject matters that support it
                        if (matter.applicable_doc_types && matter.applicable_doc_types.length > 0) {
                          return matter.applicable_doc_types.includes(documentType);
                        }
                        return true; 
                      });
                      
                      // If "Other" isn't in the list (or list is empty), inject it as a fallback
                      if (!filteredMatters.some(m => m.matter_name === 'Other')) {
                        filteredMatters.push({ matter_name: 'Other', applicable_doc_types: [] });
                      }

                      return filteredMatters.map((matter) => {
                      
                        return (
                        <label key={matter.matter_name} className={`block p-3 border rounded-lg cursor-pointer transition-all duration-200 
                          ${subjectMatter === matter.matter_name ? 'border-primary bg-primary/5' : 'border-outline-variant bg-white hover:border-primary/50'}
                        `}>
                          <div className="flex items-center gap-3">
                            <input 
                              type="radio" 
                              name="subject_matter" 
                              value={matter.matter_name} 
                              checked={subjectMatter === matter.matter_name} 
                              onChange={() => setSubjectMatter(matter.matter_name)} 
                              className="w-4 h-4 text-primary border-outline-variant focus:ring-primary" 
                            />
                            <div className="flex flex-col">
                              <span className={`text-sm font-medium ${subjectMatter === matter.matter_name ? 'text-primary' : 'text-on-surface'}`}>{matter.matter_name}</span>
                            </div>
                          </div>
                        </label>
                      );
                    });
                  })()
                  )}
                </div>
              </div>

              <div>
                <h3 className="font-bold text-on-surface mb-1">Brief Description of the Case</h3>
                <p className="text-sm text-on-surface-variant mb-4">Describe what happened and what relief you are seeking (minimum 180 words)</p>
                <textarea 
                  value={caseDescription}
                  onChange={(e) => setCaseDescription(e.target.value)}
                  placeholder="e.g. The petitioner is the recorded owner of Plot No. 45, Village Rampur. The respondent has illegally occupied the land since January 2023..." 
                  className="w-full p-4 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm transition-all resize-y min-h-[200px]" 
                />
                <div className={`text-xs mt-2 font-medium ${caseDescription.trim().split(/\s+/).filter(w => w.length > 0).length < 180 ? 'text-error' : 'text-primary'}`}>
                  {caseDescription.trim().split(/\s+/).filter(w => w.length > 0).length} words {caseDescription.trim().split(/\s+/).filter(w => w.length > 0).length < 180 ? `(${180 - caseDescription.trim().split(/\s+/).filter(w => w.length > 0).length} more needed)` : '(Minimum reached)'}
                </div>
              </div>
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
                  <textarea placeholder="1. That the petitioner is the recorded owner of... 2. That on [date], the respondent..." className="w-full p-4 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm transition-all min-h-[100px]" />
                </div>

                <div>
                  <label className="block text-sm font-bold text-on-surface mb-1">Grounds</label>
                  <p className="text-xs text-on-surface-variant mb-2">Legal grounds to be raised. Leave blank and AI will draft appropriate grounds.</p>
                  <textarea placeholder="A. That the impugned order is without jurisdiction... B. That the respondent has violated..." className="w-full p-4 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm transition-all min-h-[100px]" />
                </div>

                <div>
                  <label className="block text-sm font-bold text-on-surface mb-1">Relief Sought</label>
                  <p className="text-xs text-on-surface-variant mb-2">What you want the court to order. Leave blank for AI to draft.</p>
                  <textarea placeholder="i. Issue a writ of mandamus directing... ii. Stay the operation of..." className="w-full p-4 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm transition-all min-h-[80px]" />
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
                    {courtLevel === 'high' && selectedHighCourt ? selectedHighCourt : 
                     courtLevel === 'district' && selectedDistrictCourt ? `${selectedDistrictCourt}, ${selectedState}` : 
                     courtLevel === 'tribunal' && selectedSubLevel === 'tribunal' && selectedTribunal ? selectedTribunal :
                     courtLevel === 'tribunal' && selectedSubLevel === 'special_court' && selectedSpecialCourt ? selectedSpecialCourt :
                     `${courtLevel} Court`}
                  </span>
                  <span className="text-on-surface-variant">Document:</span>
                  <span className="font-medium text-on-surface">{documentType || 'Not selected'}</span>
                  <span className="text-on-surface-variant">Subject:</span>
                  <span className="font-medium text-on-surface">{subjectMatter || 'Not selected'}</span>
                  <span className="text-on-surface-variant">Documents confirmed:</span>
                  <span className="font-medium text-on-surface">{confirmedDocs}</span>
                </div>
              </div>
            </>
          )}

          {currentStep === 6 && generateStatus === 'loading' && (
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

          {currentStep === 6 && (generateStatus === 'streaming' || generateStatus === 'completed') && (
            <div className="flex-1 flex flex-col h-full bg-surface-container-lowest animate-fade-slide-up">
              {/* Toolbar */}
              <div className="flex items-center justify-between p-4 border-b border-outline-variant bg-white">
                <div className="flex items-center gap-2">
                  <button onClick={() => handleFormat('bold')} className="w-8 h-8 flex items-center justify-center rounded hover:bg-surface-container-low text-on-surface transition-colors" title="Bold">
                    <span className="material-symbols-outlined text-lg">format_bold</span>
                  </button>
                  <button onClick={() => handleFormat('italic')} className="w-8 h-8 flex items-center justify-center rounded hover:bg-surface-container-low text-on-surface transition-colors" title="Italic">
                    <span className="material-symbols-outlined text-lg">format_italic</span>
                  </button>
                  <button onClick={() => handleFormat('underline')} className="w-8 h-8 flex items-center justify-center rounded hover:bg-surface-container-low text-on-surface transition-colors" title="Underline">
                    <span className="material-symbols-outlined text-lg">format_underlined</span>
                  </button>
                  <div className="w-px h-6 bg-outline-variant mx-1"></div>
                  <button onClick={() => handleFormat('justifyLeft')} className="w-8 h-8 flex items-center justify-center rounded hover:bg-surface-container-low text-on-surface transition-colors">
                    <span className="material-symbols-outlined text-lg">format_align_left</span>
                  </button>
                  <button onClick={() => handleFormat('justifyCenter')} className="w-8 h-8 flex items-center justify-center rounded hover:bg-surface-container-low text-on-surface transition-colors">
                    <span className="material-symbols-outlined text-lg">format_align_center</span>
                  </button>
                  <button onClick={() => handleFormat('justifyFull')} className="w-8 h-8 flex items-center justify-center rounded hover:bg-surface-container-low text-on-surface transition-colors">
                    <span className="material-symbols-outlined text-lg">format_align_justify</span>
                  </button>
                </div>
                
                <div className="flex items-center gap-3">
                  <span className={`text-xs font-bold px-3 py-1 rounded-full ${generateStatus === 'completed' ? 'bg-[#004131]/10 text-[#004131]' : 'bg-primary text-white animate-pulse'}`}>
                    {generateStatusText}
                  </span>
                  <button onClick={() => setIsEditingMode(!isEditingMode)} className={`flex items-center gap-2 px-3 py-1.5 text-sm font-bold rounded transition-colors ${isEditingMode ? 'bg-primary text-white' : 'bg-surface-container-low text-on-surface hover:bg-surface-container'}`}>
                    <span className="material-symbols-outlined text-[16px]">{isEditingMode ? 'visibility' : 'edit'}</span>
                    {isEditingMode ? 'Preview Mode' : 'Edit Text'}
                  </button>
                  <button onClick={handleDownloadPDF} className="flex items-center gap-2 px-4 py-1.5 bg-primary text-white text-sm font-bold rounded hover:bg-[#004131] transition-colors">
                    <span className="material-symbols-outlined text-[16px]">download</span>
                    PDF
                  </button>
                </div>
              </div>

              {/* Editor Workspace */}
              <div className="flex-1 overflow-y-auto bg-surface-container-lowest p-8 md:p-12 print:p-0 print:bg-white">
                <div 
                  className="max-w-[850px] mx-auto bg-white shadow-xl min-h-[1123px] border border-outline-variant print:shadow-none print:border-none print:m-0 print:max-w-none"
                  style={{ 
                    boxShadow: '0 10px 25px rgba(0,0,0,0.05), 0 0 1px rgba(0,0,0,0.1)',
                    paddingTop: '1in',
                    paddingRight: '1in',
                    paddingBottom: '1in',
                    paddingLeft: courtLevel === 'supreme' ? '2in' : courtLevel === 'high' ? '1.5in' : '1in'
                  }}
                >
                  <div 
                    ref={editorRef}
                    className="text-on-surface outline-none prose prose-slate max-w-none"
                    style={{ 
                      fontFamily: '"Times New Roman", Times, serif', 
                      fontSize: courtLevel === 'supreme' || courtLevel === 'high' ? '14pt' : '12pt',
                      lineHeight: '1.5'
                    }}
                  >
                    {isEditingMode ? (
                      <textarea
                        value={draftContent}
                        onChange={(e) => setDraftContent(e.target.value)}
                        className="w-full h-full min-h-[1000px] bg-transparent resize-none outline-none font-mono"
                        style={{ fontSize: '11pt', lineHeight: '1.6' }}
                        spellCheck={false}
                      />
                    ) : (
                      <ReactMarkdown 
                        remarkPlugins={[remarkGfm]}
                        rehypePlugins={[rehypeRaw]}
                        components={{
                          hr: ({node, ...props}) => <hr className="border-0 border-b border-dashed border-outline-variant w-full print:border-transparent print:m-0" style={{ margin: '2rem 0', pageBreakAfter: 'always', breakAfter: 'page' }} {...props} />,
                          table: ({node, ...props}) => <table className="w-full text-left border-collapse border border-outline-variant my-6" {...props} />,
                          th: ({node, ...props}) => <th className="border border-outline-variant px-4 py-2 bg-surface-container-low font-bold" {...props} />,
                          td: ({node, ...props}) => <td className="border border-outline-variant px-4 py-2" {...props} />,
                          h1: ({node, ...props}) => <h1 className="text-center font-bold uppercase mb-6" style={{ fontSize: '16pt', margin: '1.5rem 0 1rem 0', fontFamily: '"Times New Roman", Times, serif' }} {...props} />,
                          h2: ({node, ...props}) => <h2 className="text-center font-bold uppercase mt-8 mb-4" style={{ fontSize: '14pt', margin: '1.5rem 0 1rem 0', fontFamily: '"Times New Roman", Times, serif' }} {...props} />,
                          h3: ({node, ...props}) => <h3 className="font-bold uppercase mt-6 mb-3" style={{ fontSize: '14pt', margin: '1.2rem 0 0.6rem 0', fontFamily: '"Times New Roman", Times, serif' }} {...props} />,
                          p: ({node, ...props}) => <p className="whitespace-pre-wrap" style={{ marginBottom: '1rem', marginTop: 0, textAlign: 'justify', textJustify: 'inter-word', lineHeight: '1.5' }} {...props} />,
                          ul: ({node, ...props}) => <ul className="list-disc pl-6 my-3" style={{ margin: '0.5rem 0 0.5rem 1.5rem' }} {...props} />,
                          ol: ({node, ...props}) => <ol className="list-decimal pl-6 my-3" style={{ margin: '0.5rem 0 0.5rem 1.5rem' }} {...props} />,
                          li: ({node, ...props}) => <li style={{ margin: '0.3rem 0', lineHeight: '1.5', textAlign: 'justify' }} {...props} />
                        }}
                      >
                        {draftContent}
                      </ReactMarkdown>
                    )}
                  </div>
                </div>
              </div>

              {/* Citation Verification Panel */}
              {citations.length > 0 && (
                <div className="border-t border-outline-variant bg-surface-container-lowest px-8 py-5">
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
        {!(currentStep === 6 && generateStatus !== 'loading' && generateStatus !== 'idle') && (
          <div className="mt-8 flex justify-between items-center">
            <button 
              onClick={handleBack}
              disabled={currentStep === 1}
              className={`flex items-center gap-2 px-6 py-2.5 rounded-lg border font-bold transition-all ${currentStep === 1 ? 'border-outline-variant/50 text-outline cursor-not-allowed bg-transparent' : 'border-outline-variant text-on-surface bg-white hover:bg-surface-container-low hover:shadow-sm'}`}>
              <span className="material-symbols-outlined text-sm">arrow_back</span>
              Back
            </button>
            
            {currentStep < 6 ? (
              <button 
                onClick={handleNext}
                disabled={
                  (currentStep === 1 && courtLevel === 'high' && !selectedHighCourt) ||
                  (currentStep === 1 && courtLevel === 'district' && (!selectedState || !selectedDistrictCourt)) ||
                  (currentStep === 1 && courtLevel === 'tribunal' && (
                    !selectedSubLevel ||
                    (selectedSubLevel === 'tribunal' && !selectedTribunal) ||
                    (selectedSubLevel === 'special_court' && !selectedSpecialCourt)
                  )) ||
                  (currentStep === 3 && (
                    !subjectMatter ||
                    caseDescription.trim().split(/\s+/).filter(w => w.length > 0).length < 180
                  ))
                }
                className="flex items-center gap-2 bg-primary text-white px-8 py-3 rounded-lg font-bold shadow-md hover:-translate-y-0.5 hover:shadow-lg hover:bg-[#004131] active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:translate-y-0 transition-all duration-300">
                Next
                <span className="material-symbols-outlined text-sm">arrow_forward</span>
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
