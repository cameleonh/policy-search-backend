"use client";

import { useState, type ChangeEvent, type FormEvent } from "react";
import type { SearchProfile, SearchResult } from "@policy-search/contracts";

interface SearchResponse {
  data_version: string;
  results: SearchResult[];
  total: number;
  page: number;
  page_size: number;
  rag_enabled: boolean;
}

export default function SearchPage() {
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);

  // Individual fields
  const [birthDate, setBirthDate] = useState("");
  const [region, setRegion] = useState("");
  const [employmentStatus, setEmploymentStatus] = useState("");
  const [incomeBracket, setIncomeBracket] = useState("");

  // Business fields
  const [isBusinessOwner, setIsBusinessOwner] = useState(false);
  const [businessRegion, setBusinessRegion] = useState("");
  const [industry, setIndustry] = useState("");
  const [annualRevenue, setAnnualRevenue] = useState("");
  const [employeeCount, setEmployeeCount] = useState("");

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const profile: SearchProfile = {
      birthDate: birthDate || undefined,
      region: region || undefined,
      employmentStatus: employmentStatus || undefined,
      incomeBracket: incomeBracket || undefined,
      isBusinessOwner,
      businessRegion: businessRegion || undefined,
      industry: industry || undefined,
      annualRevenue: annualRevenue ? Number(annualRevenue) : undefined,
      employeeCount: employeeCount ? Number(employeeCount) : undefined,
    };

    try {
      const res = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(profile),
      });
      if (!res.ok) throw new Error(`Search failed: ${res.status}`);
      const data = (await res.json()) as SearchResponse;
      setResults(data.results);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main style={{ maxWidth: 900, margin: "0 auto", padding: 24 }}>
      <h1>정책 검색</h1>
      <p style={{ color: "#666", marginBottom: 24 }}>
        청년 개인 지원과 소상공인 사업체 지원을 한 번에 검색하세요.
      </p>

      <form onSubmit={handleSubmit} style={{ marginBottom: 32 }}>
        <fieldset style={{ marginBottom: 16, padding: 16, border: "1px solid #ddd", borderRadius: 8 }}>
          <legend style={{ fontWeight: "bold" }}>개인 정보</legend>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <label>
              생년월일
              <input type="date" value={birthDate} onChange={(e: ChangeEvent<HTMLInputElement>) => setBirthDate(e.target.value)} style={{ width: "100%", padding: 8 }} />
            </label>
            <label>
              거주 지역
              <input type="text" value={region} onChange={(e: ChangeEvent<HTMLInputElement>) => setRegion(e.target.value)} placeholder="예: 서울특별시" style={{ width: "100%", padding: 8 }} />
            </label>
            <label>
              취업 상태
              <select value={employmentStatus} onChange={(e: ChangeEvent<HTMLSelectElement>) => setEmploymentStatus(e.target.value)} style={{ width: "100%", padding: 8 }}>
                <option value="">선택 안함</option>
                <option value="미취업">미취업</option>
                <option value="재직중">재직중</option>
                <option value="자영업">자영업</option>
              </select>
            </label>
            <label>
              소득 구간
              <select value={incomeBracket} onChange={(e: ChangeEvent<HTMLSelectElement>) => setIncomeBracket(e.target.value)} style={{ width: "100%", padding: 8 }}>
                <option value="">선택 안함</option>
                <option value="전액">전액</option>
                <option value="3000만원 이하">3000만원 이하</option>
                <option value="5000만원 이하">5000만원 이하</option>
              </select>
            </label>
          </div>
        </fieldset>

        <fieldset style={{ marginBottom: 16, padding: 16, border: "1px solid #ddd", borderRadius: 8 }}>
          <legend style={{ fontWeight: "bold" }}>
            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input type="checkbox" checked={isBusinessOwner} onChange={(e: ChangeEvent<HTMLInputElement>) => setIsBusinessOwner(e.target.checked)} />
              사업체 정보
            </label>
          </legend>
          {isBusinessOwner && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <label>
                사업장 소재지
                <input type="text" value={businessRegion} onChange={(e: ChangeEvent<HTMLInputElement>) => setBusinessRegion(e.target.value)} style={{ width: "100%", padding: 8 }} />
              </label>
              <label>
                업종
                <input type="text" value={industry} onChange={(e: ChangeEvent<HTMLInputElement>) => setIndustry(e.target.value)} style={{ width: "100%", padding: 8 }} />
              </label>
              <label>
                연 매출 (만원)
                <input type="number" value={annualRevenue} onChange={(e: ChangeEvent<HTMLInputElement>) => setAnnualRevenue(e.target.value)} style={{ width: "100%", padding: 8 }} />
              </label>
              <label>
                상시근로자 수
                <input type="number" value={employeeCount} onChange={(e: ChangeEvent<HTMLInputElement>) => setEmployeeCount(e.target.value)} style={{ width: "100%", padding: 8 }} />
              </label>
            </div>
          )}
        </fieldset>

        <button
          type="submit"
          disabled={loading}
          style={{ padding: "12px 32px", fontSize: 16, cursor: loading ? "wait" : "pointer" }}
        >
          {loading ? "검색 중..." : "검색"}
        </button>
      </form>

      {error && <p style={{ color: "red" }}>{error}</p>}

      {results.length > 0 && (
        <div>
          <p style={{ marginBottom: 16 }}>총 {total}건</p>
          {results.map((result) => (
            <ResultCard key={result.policyVersion.programId} result={result} />
          ))}
        </div>
      )}

      {!loading && results.length === 0 && total === 0 && (
        <p style={{ color: "#999" }}>검색 결과가 여기에 표시됩니다.</p>
      )}
    </main>
  );
}

function ResultCard({ result }: { result: SearchResult }) {
  const isEligible = result.triState === "eligible";
  const statusText = isEligible ? "지원 가능" : "가능성 있음";
  const statusColor = isEligible ? "#16a34a" : "#ca8a04";

  return (
    <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 16, marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
        <div>
          <h3 style={{ margin: 0, marginBottom: 4 }}>{result.policyVersion.title}</h3>
          <p style={{ color: "#666", fontSize: 14, margin: 0 }}>
            {result.policyVersion.targetType === "individual" ? "개인 지원" : result.policyVersion.targetType === "business" ? "사업체 지원" : "개인·사업체"}
            {" · "}
            {result.policyVersion.announcementUrl && (
              <a href={result.policyVersion.announcementUrl} target="_blank" rel="noopener noreferrer">
                공식 공고
              </a>
            )}
          </p>
        </div>
        <span style={{ color: statusColor, fontWeight: "bold", whiteSpace: "nowrap" }}>{statusText}</span>
      </div>

      {result.reasons.length > 0 && (
        <ul style={{ marginTop: 8, paddingLeft: 20, fontSize: 14 }}>
          {result.reasons.map((reason, i) => (
            <li key={i}>{reason}</li>
          ))}
        </ul>
      )}

      {result.missingInfo.length > 0 && (
        <p style={{ fontSize: 14, color: "#ca8a04", marginTop: 8 }}>
          확인 필요: {result.missingInfo.join(", ")}
        </p>
      )}

      {result.benefits.length > 0 && (
        <p style={{ fontSize: 14, marginTop: 8 }}>혜택: {result.benefits.join(", ")}</p>
      )}

      {result.applicationDeadline && (
        <p style={{ fontSize: 14, marginTop: 8 }}>신청 마감: {result.applicationDeadline}</p>
      )}

      {result.evidenceRefs.length > 0 && (
        <p style={{ fontSize: 12, color: "#999", marginTop: 8 }}>
          근거: {result.evidenceRefs.join(", ")}
        </p>
      )}
    </div>
  );
}
