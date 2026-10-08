'use client';
/** SDD 5.13 metrics route. 평가 지표는 운영자 전용이다 (일반 사용자에게 모델 비교·비용은 필요 없다). */
import {MetricsPage} from '@/components/MetricsPage';
import {OperatorOnly} from '@/components/OperatorOnly';
export default function MetricsRoute() { return <OperatorOnly><MetricsPage/></OperatorOnly>; }
