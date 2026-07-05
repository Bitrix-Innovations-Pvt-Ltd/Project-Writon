'use client';

import { useState, useEffect, useRef } from 'react';
import Navbar from '@/components/shared/Navbar';
import Link from 'next/link';

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

export default function DraftWizard() {
  const [currentStep, setCurrentStep] = useState(1);
  const [courtLevel, setCourtLevel] = useState('supreme');
  const [documentType, setDocumentType] = useState('');
  const [subjectMatter, setSubjectMatter] = useState('');
  const [caseDescription, setCaseDescription] = useState('');
  const [uploadedDocs, setUploadedDocs] = useState<Record<string, string>>({}); 

  const [selectedHighCourt, setSelectedHighCourt] = useState('');
  const [selectedState, setSelectedState] = useState('');
  const [selectedDistrictCourt, setSelectedDistrictCourt] = useState('');
  const [selectedSubLevel, setSelectedSubLevel] = useState<'tribunal' | 'special_court' | ''>('');
  const [selectedTribunal, setSelectedTribunal] = useState('');
  const [selectedSpecialCourt, setSelectedSpecialCourt] = useState('');

  // Generation state
  const [generateStatus, setGenerateStatus] = useState<'idle' | 'loading' | 'streaming' | 'completed'>('idle');
  const [draftContent, setDraftContent] = useState('');
  const editorRef = useRef<HTMLDivElement>(null);

  const steps = [
    { num: 1, label: 'Court & Level' },
    { num: 2, label: 'Document Type' },
    { num: 3, label: 'Subject Matter' },
    { num: 4, label: 'Documents' },
    { num: 5, label: 'Parties & Facts' },
    { num: 6, label: 'Generate' },
  ];

  const documentTypes = [
    'Writ Petition (Art. 32)',
    'Special Leave Petition',
    'Transfer Petition',
    'Review Petition',
    'Curative Petition',
    'Original Suit (Art. 131)'
  ];

  const subjectMatters = [
    'Property / Land Dispute', 'Criminal Matter',
    'Service / Employment', 'Matrimonial / Family',
    'Consumer Complaint', 'Motor Accident',
    'Cheque Dishonour (NI Act)', 'Bail / Anticipatory Bail',
    'Writ / Fundamental Rights', 'Company / NCLT',
    'Income Tax / GST', 'Environmental',
    'Other'
  ];

  const requiredDocs = [
    { id: 'assessment', title: 'Assessment Order', desc: 'Order passed by Assessing Officer / GST authority' },
    { id: 'scn', title: 'Show Cause Notice', desc: 'Notice issued before the assessment / demand' },
    { id: 'appeal', title: 'First Appeal Order (CIT(A) / GST Appellate)', desc: 'Order of first appellate authority' },
    { id: 'returns', title: 'IT Returns / GST Returns', desc: 'Returns for the relevant assessment years' },
  ];

  const optionalDocs = [
    { id: 'reply', title: 'Reply Filed to SCN', desc: 'Reply filed by assessee to SCN' },
    { id: 'books', title: 'Books of Accounts / Audit Report', desc: 'Supporting financial records' },
    { id: 'challan', title: 'Challan of Tax Deposited', desc: 'If any amount deposited under protest' },
  ];

  const totalDocs = requiredDocs.length + optionalDocs.length;
  const confirmedDocs = Object.keys(uploadedDocs).length;

  const handleNext = () => {
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

  const setDocStatus = (id: string, status: string) => {
    setUploadedDocs(prev => ({ ...prev, [id]: status }));
  };

  const startGeneration = () => {
    setGenerateStatus('loading');
    setTimeout(() => {
      setGenerateStatus('streaming');
      simulateStreaming();
    }, 2500); // Simulate processing time before streaming starts
  };

  const simulateStreaming = () => {
    const dummyText = `IN THE SUPREME COURT OF INDIA
ORIGINAL JURISDICTION
WRIT PETITION (CIVIL) NO. _____ OF 2024

IN THE MATTER OF:
[Petitioner Name] ... Petitioner

VERSUS

[Respondent Name] ... Respondent

TO
THE HON'BLE CHIEF JUSTICE OF INDIA AND HIS COMPANION JUSTICES OF THE SUPREME COURT OF INDIA.

The humble petition of the Petitioner abovenamed MOST RESPECTFULLY SHOWETH:

1. That the Petitioner is filing this Writ Petition under Article 32 of the Constitution of India for the issuance of a writ of Mandamus or any other appropriate writ, order or direction to protect the fundamental rights of the Petitioner guaranteed under Article 14, 19 and 21.

2. BRIEF FACTS: 
That the facts giving rise to the present writ petition are that on 12th March 2023, the respondent authorities arbitrarily and without any prior notice initiated coercive action against the petitioner.

3. GROUNDS:
A. Because the impugned action of the respondent is wholly arbitrary, illegal and violative of the principles of natural justice.
B. Because the respondent authority has acted in excess of its jurisdiction.
C. Because the action violates the petitioner's fundamental right to equality before the law as enshrined under Article 14 of the Constitution.

PRAYER:
In view of the facts and circumstances stated above, it is most respectfully prayed that this Hon'ble Court may be pleased to:
a) Issue a writ of mandamus or any other appropriate writ, order or direction quashing the impugned notice dated 12.03.2023.
b) Pass any other order which this Hon'ble Court may deem fit and proper in the interest of justice.`;

    let currentIndex = 0;
    setDraftContent('');
    
    const intervalId = setInterval(() => {
      setDraftContent((prev) => {
        const nextContent = prev + dummyText.charAt(currentIndex);
        currentIndex++;
        if (currentIndex >= dummyText.length) {
          clearInterval(intervalId);
          setGenerateStatus('completed');
        }
        return nextContent;
      });
      
      // Auto-scroll the editor to the bottom while streaming
      if (editorRef.current) {
        editorRef.current.scrollTop = editorRef.current.scrollHeight;
      }
    }, 15); // Adjust speed here (ms per char)
  };

  const handleFormat = (command: string) => {
    document.execCommand(command, false, '');
    if (editorRef.current) {
      editorRef.current.focus();
    }
  };

  return (
    <div className="font-body-md text-body-md bg-surface min-h-screen text-on-surface flex flex-col">
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
                {documentTypes.map((type) => (
                  <label key={type} className={`block p-4 border rounded-lg cursor-pointer transition-all duration-200 hover:shadow-sm ${documentType === type ? 'border-primary bg-primary/5 shadow-[0_0_0_2px_rgba(14,107,82,0.1)]' : 'border-outline-variant bg-white hover:border-primary/50'}`}>
                    <div className="flex items-center gap-4">
                      <input type="radio" name="document_type" value={type} checked={documentType === type} onChange={() => setDocumentType(type)} className="w-5 h-5 text-primary border-outline-variant focus:ring-primary" />
                      <span className={`font-medium ${documentType === type ? 'text-primary' : 'text-on-surface'}`}>{type}</span>
                    </div>
                  </label>
                ))}
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
                  {subjectMatters.map((matter) => (
                    <label key={matter} className={`block p-3 border rounded-lg cursor-pointer transition-all duration-200 ${subjectMatter === matter ? 'border-primary bg-primary/5' : 'border-outline-variant bg-white hover:border-primary/50'}`}>
                      <div className="flex items-center gap-3">
                        <input type="radio" name="subject_matter" value={matter} checked={subjectMatter === matter} onChange={() => setSubjectMatter(matter)} className="w-4 h-4 text-primary border-outline-variant focus:ring-primary" />
                        <span className={`text-sm font-medium ${subjectMatter === matter ? 'text-primary' : 'text-on-surface'}`}>{matter}</span>
                      </div>
                    </label>
                  ))}
                </div>
              </div>

              <div>
                <h3 className="font-bold text-on-surface mb-1">Brief Description of the Case</h3>
                <p className="text-sm text-on-surface-variant mb-4">Describe what happened and what relief you are seeking (minimum 20 characters)</p>
                <textarea 
                  value={caseDescription}
                  onChange={(e) => setCaseDescription(e.target.value)}
                  placeholder="e.g. The petitioner is the recorded owner of Plot No. 45, Village Rampur. The respondent has illegally occupied the land since January 2023..." 
                  className="w-full p-4 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm transition-all resize-y min-h-[120px]" 
                />
                <div className={`text-xs mt-2 font-medium ${caseDescription.length < 20 ? 'text-error' : 'text-primary'}`}>
                  {caseDescription.length} characters {caseDescription.length < 20 ? `(${20 - caseDescription.length} more needed)` : '(Minimum reached)'}
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
                {/* Required Documents */}
                <div>
                  <div className="flex items-center gap-3 mb-4">
                    <span className="bg-error/10 text-error px-2 py-1 rounded text-xs font-bold tracking-wider">REQUIRED</span>
                    <span className="text-sm text-on-surface-variant">Must have before filing</span>
                  </div>
                  <div className="space-y-4">
                    {requiredDocs.map(doc => (
                      <div key={doc.id} className={`p-4 border rounded-xl flex flex-col sm:flex-row sm:items-center justify-between gap-4 transition-all ${uploadedDocs[doc.id] === 'uploaded' ? 'border-primary bg-primary/5' : uploadedDocs[doc.id] === 'unavailable' ? 'border-outline-variant bg-surface-container-low opacity-75' : 'border-outline-variant bg-white'}`}>
                        <div>
                          <div className="flex items-center gap-2 mb-1">
                            {uploadedDocs[doc.id] === 'uploaded' && <span className="material-symbols-outlined text-primary text-sm font-bold">check_circle</span>}
                            <h4 className={`font-bold ${uploadedDocs[doc.id] === 'uploaded' ? 'text-primary' : 'text-on-surface'}`}>{doc.title}</h4>
                          </div>
                          <p className="text-xs text-on-surface-variant">{doc.desc}</p>
                        </div>
                        <div className="flex items-center gap-2">
                          <button 
                            onClick={() => setDocStatus(doc.id, 'unavailable')}
                            className={`px-3 py-1.5 text-xs font-semibold rounded-lg border transition-colors ${uploadedDocs[doc.id] === 'unavailable' ? 'bg-surface-container-highest border-outline text-on-surface' : 'bg-white border-outline-variant text-on-surface-variant hover:bg-surface-container-low'}`}
                          >
                            Not Available
                          </button>
                          <label className={`cursor-pointer px-4 py-1.5 text-xs font-bold rounded-lg border transition-colors flex items-center gap-2 ${uploadedDocs[doc.id] === 'uploaded' ? 'bg-primary border-primary text-white' : 'bg-surface border-outline-variant text-primary hover:bg-primary/5 hover:border-primary/50'}`}>
                            <span className="material-symbols-outlined text-[16px]">upload</span>
                            {uploadedDocs[doc.id] === 'uploaded' ? 'Uploaded' : 'Upload'}
                            <input type="file" className="hidden" onChange={(e) => { if (e.target.files?.length) setDocStatus(doc.id, 'uploaded') }} />
                          </label>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Optional Documents */}
                <div>
                  <div className="flex items-center gap-3 mb-4">
                    <span className="bg-[#E4C853]/20 text-[#715000] px-2 py-1 rounded text-xs font-bold tracking-wider">OPTIONAL</span>
                    <span className="text-sm text-on-surface-variant">Strengthens your case</span>
                  </div>
                  <div className="space-y-4">
                    {optionalDocs.map(doc => (
                      <div key={doc.id} className={`p-4 border rounded-xl flex flex-col sm:flex-row sm:items-center justify-between gap-4 transition-all ${uploadedDocs[doc.id] === 'uploaded' ? 'border-primary bg-primary/5' : uploadedDocs[doc.id] === 'unavailable' ? 'border-outline-variant bg-surface-container-low opacity-75' : 'border-outline-variant bg-white'}`}>
                        <div>
                          <div className="flex items-center gap-2 mb-1">
                            {uploadedDocs[doc.id] === 'uploaded' && <span className="material-symbols-outlined text-primary text-sm font-bold">check_circle</span>}
                            <h4 className={`font-bold ${uploadedDocs[doc.id] === 'uploaded' ? 'text-primary' : 'text-on-surface'}`}>{doc.title}</h4>
                          </div>
                          <p className="text-xs text-on-surface-variant">{doc.desc}</p>
                        </div>
                        <div className="flex items-center gap-2">
                          <button 
                            onClick={() => setDocStatus(doc.id, 'unavailable')}
                            className={`px-3 py-1.5 text-xs font-semibold rounded-lg border transition-colors ${uploadedDocs[doc.id] === 'unavailable' ? 'bg-surface-container-highest border-outline text-on-surface' : 'bg-white border-outline-variant text-on-surface-variant hover:bg-surface-container-low'}`}
                          >
                            Not Available
                          </button>
                          <label className={`cursor-pointer px-4 py-1.5 text-xs font-bold rounded-lg border transition-colors flex items-center gap-2 ${uploadedDocs[doc.id] === 'uploaded' ? 'bg-primary border-primary text-white' : 'bg-surface border-outline-variant text-primary hover:bg-primary/5 hover:border-primary/50'}`}>
                            <span className="material-symbols-outlined text-[16px]">upload</span>
                            {uploadedDocs[doc.id] === 'uploaded' ? 'Uploaded' : 'Upload'}
                            <input type="file" className="hidden" onChange={(e) => { if (e.target.files?.length) setDocStatus(doc.id, 'uploaded') }} />
                          </label>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </>
          )}

          {currentStep === 5 && (
            <>
              <div className="mb-8">
                <h2 className="font-display-lg text-2xl font-bold text-on-surface mb-1">Parties & Facts</h2>
              </div>
              
              <div className="space-y-6">
                <div>
                  <label className="block text-sm font-bold text-on-surface mb-1">Petitioner / Appellant / Complainant *</label>
                  <input type="text" placeholder="Full name, s/o, d/o, R/o... (e.g. Ramesh Kumar, s/o Suresh Kumar, R/o Village Rampur, Dist. Lucknow)" className="w-full p-3 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm transition-all" />
                </div>
                
                <div>
                  <label className="block text-sm font-bold text-on-surface mb-1">Respondent / Opposite Party *</label>
                  <input type="text" placeholder="Full name or designation (e.g. State of U.P. through Principal Secretary, Revenue)" className="w-full p-3 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm transition-all" />
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
                    {generateStatus === 'completed' ? 'Generation Complete' : 'Streaming AI Draft...'}
                  </span>
                  <button className="flex items-center gap-2 px-4 py-1.5 bg-primary text-white text-sm font-bold rounded hover:bg-[#004131] transition-colors">
                    <span className="material-symbols-outlined text-[16px]">download</span>
                    PDF
                  </button>
                </div>
              </div>

              {/* Editor Workspace */}
              <div className="flex-1 overflow-y-auto bg-surface-container-lowest p-8 md:p-12">
                <div 
                  className="max-w-[800px] mx-auto bg-white shadow-xl min-h-[1056px] p-12 md:p-16 border border-outline-variant"
                  style={{ boxShadow: '0 10px 25px rgba(0,0,0,0.05), 0 0 1px rgba(0,0,0,0.1)' }}
                >
                  <div 
                    ref={editorRef}
                    className="font-body-lg text-on-surface outline-none prose prose-slate max-w-none whitespace-pre-wrap leading-loose"
                    contentEditable
                    suppressContentEditableWarning
                    style={{ fontFamily: 'var(--font-serif)', fontSize: '1.1rem' }}
                  >
                    {draftContent}
                  </div>
                </div>
              </div>
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
