import Link from "next/link";

export default function HomePage() {
  return (
    <main>
      <h1>Policy Search</h1>
      <p>Unified youth and small-business policy search platform.</p>
      <Link
        href="/search"
        style={{
          display: "inline-block",
          marginTop: 16,
          padding: "8px 16px",
          background: "#0070f3",
          color: "white",
          borderRadius: 4,
          textDecoration: "none",
        }}
      >
        정책 검색하기 →
      </Link>
    </main>
  );
}
