import io, time, httpx
from PIL import Image
Image.MAX_IMAGE_PIXELS=None
for n in (10000, 13000, 14000):
    b=io.BytesIO(); Image.new("L",(n,n),255).save(b,"PNG")
    t=time.time(); r=httpx.post("http://localhost:8100/api/document/bl",files={"file":("a.png",b.getvalue(),"image/png")},timeout=120)
    print(n, len(b.getvalue()), r.status_code, round(time.time()-t,1), r.text[:100])
