'use client';
/** Marvia 소개 페이지 (로그인한 사람이 사이드바에서 연다). 본문은 로그인 전 첫 화면과 같은 IntroContent 하나를 쓴다.
 * 여기서는 시작 버튼만 다르다: 이미 로그인했으니 구글 로그인 대신 조회 화면(/)으로 보낸다.
 */
import Link from 'next/link';
import {IntroContent} from '@/components/IntroContent';

export default function AboutPage() {
  return <IntroContent action={<Link href="/" className="intro-btn">시작하기</Link>}/>;
}
