-- 근거 링크(source_url)를 사이트 틀이 있는 법령·고시 페이지로 바꾼다 (11-26).
-- 바꾸기 전: lsInfoR.do, admRulInfoR.do는 본문 조각만 주는 주소다. 바꾼 뒤: 같은 판의 lsInfoP.do, admRulInfoP.do.
-- 별표(lsBylInfoPLinkR.do)는 이미 틀이 있는 페이지라 건드리지 않는다. 여러 번 돌려도 같다.
BEGIN;
UPDATE corpus_units
SET source_url = replace(
        replace(source_url, '/LSW/lsInfoR.do?lsiSeq=', '/LSW/lsInfoP.do?lsiSeq='),
        '&chrClsCd=010202&urlMode=lsInfoP', '')
WHERE source_url LIKE 'https://www.law.go.kr/LSW/lsInfoR.do?lsiSeq=%';
UPDATE corpus_units
SET source_url = replace(source_url, '/LSW/admRulInfoR.do?admRulSeq=', '/LSW/admRulInfoP.do?admRulSeq=')
WHERE source_url LIKE 'https://www.law.go.kr/LSW/admRulInfoR.do?admRulSeq=%';
-- 확인: 둘 다 0이어야 한다
SELECT count(*) AS bare_left FROM corpus_units WHERE source_url ~ '/LSW/(lsInfoR|admRulInfoR)\.do';
COMMIT;
