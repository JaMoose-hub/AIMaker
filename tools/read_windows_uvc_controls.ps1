<# Read DirectShow UVC controls without starting a capture graph or changing
   properties. No Set calls, format negotiation, camera restart or defaults.
   Reference: https://learn.microsoft.com/en-us/windows/win32/directshow/configure-the-video-quality
   Driver values/flags are evidence, not a guarantee of image quality. #>
[CmdletBinding()]
param([string]$DeviceName = 'HD Pro Webcam C920', [string]$OutPath)
$ErrorActionPreference = 'Stop'
if ($OutPath -and (Test-Path -LiteralPath $OutPath)) { throw 'Output already exists' }
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
namespace BoardVisionUvcDiagnostics {
 [ComImport, Guid("29840822-5B84-11D0-BD3B-00A0C911CE86"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
 interface ICreateDevEnum { [PreserveSig] int CreateClassEnumerator(ref Guid category, out IEnumMoniker result, int flags); }
 [ComImport, Guid("55272A00-42CB-11CE-8135-00AA004BB851"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
 interface IPropertyBag {
  [PreserveSig] int Read([MarshalAs(UnmanagedType.LPWStr)] string name, [MarshalAs(UnmanagedType.Struct)] out object value, IntPtr errorLog);
  [PreserveSig] int Write([MarshalAs(UnmanagedType.LPWStr)] string name, [MarshalAs(UnmanagedType.Struct)] ref object value);
 }
 [ComImport, Guid("C6E13360-30AC-11D0-A18C-00A0C9118956"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
 interface IAMVideoProcAmp {
  [PreserveSig] int GetRange(int property, out int min, out int max, out int step, out int def, out int caps);
  [PreserveSig] int Set(int property, int value, int flags);
  [PreserveSig] int Get(int property, out int value, out int flags);
 }
 [ComImport, Guid("C6E13370-30AC-11D0-A18C-00A0C9118956"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
 interface IAMCameraControl {
  [PreserveSig] int GetRange(int property, out int min, out int max, out int step, out int def, out int caps);
  [PreserveSig] int Set(int property, int value, int flags);
  [PreserveSig] int Get(int property, out int value, out int flags);
 }
 public class Control {
  public string Name; public int? Value, Flags, Minimum, Maximum, Step, Default, Capabilities;
  public int ReadHresult, RangeHresult;
 }
 public class Snapshot {
  public string DeviceName; public int EnumerationIndex; public List<Control> Controls = new List<Control>();
 }
 public static class Reader {
  static void Release(object obj) { if (obj != null && Marshal.IsComObject(obj)) Marshal.ReleaseComObject(obj); }
  static Control Read(object filter, string name, int property, bool camera) {
   Control result = new Control { Name = name };
   int value=0, flags=0, min=0, max=0, step=0, def=0, caps=0;
   try {
    if (camera) {
     var controls=(IAMCameraControl)filter;
     result.ReadHresult=controls.Get(property,out value,out flags);
     result.RangeHresult=controls.GetRange(property,out min,out max,out step,out def,out caps);
    } else {
     var controls=(IAMVideoProcAmp)filter;
     result.ReadHresult=controls.Get(property,out value,out flags);
     result.RangeHresult=controls.GetRange(property,out min,out max,out step,out def,out caps);
    }
    if(result.ReadHresult>=0) { result.Value=value; result.Flags=flags; }
    if(result.RangeHresult>=0) { result.Minimum=min; result.Maximum=max; result.Step=step; result.Default=def; result.Capabilities=caps; }
   } catch(COMException error) { result.ReadHresult=error.ErrorCode; result.RangeHresult=error.ErrorCode; }
   catch(InvalidCastException error) { result.ReadHresult=error.HResult; result.RangeHresult=error.HResult; }
   return result;
  }
  public static Snapshot[] Get(string selectedName) {
   object system=null; IEnumMoniker enumerator=null; var matches=new List<Snapshot>();
   try {
    system=Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("62BE5D10-60EB-11D0-BD3B-00A0C911CE86")));
    Guid category=new Guid("860BB310-5D01-11D0-BD3B-00A0C911CE86");
    int hr=((ICreateDevEnum)system).CreateClassEnumerator(ref category,out enumerator,0);
    if(hr!=0 || enumerator==null) throw new InvalidOperationException("No video input devices: " + hr);
    var item=new IMoniker[1]; int index=0;
    while(enumerator.Next(1,item,IntPtr.Zero)==0) {
     object bag=null, filter=null;
     try {
      Guid bagId=typeof(IPropertyBag).GUID;
      item[0].BindToStorage(null,null,ref bagId,out bag);
      object name;
      if(((IPropertyBag)bag).Read("FriendlyName",out name,IntPtr.Zero)==0 && String.Equals((string)name,selectedName,StringComparison.OrdinalIgnoreCase)) {
       Guid filterId=new Guid("56A86895-0AD4-11CE-B03A-0020AF0BA770");
       item[0].BindToObject(null,null,ref filterId,out filter);
       var snapshot=new Snapshot { DeviceName=(string)name, EnumerationIndex=index };
       snapshot.Controls.Add(Read(filter,"exposure",4,true));
       snapshot.Controls.Add(Read(filter,"focus",6,true));
       snapshot.Controls.Add(Read(filter,"brightness",0,false));
       snapshot.Controls.Add(Read(filter,"contrast",1,false));
       snapshot.Controls.Add(Read(filter,"saturation",3,false));
       snapshot.Controls.Add(Read(filter,"sharpness",4,false));
       snapshot.Controls.Add(Read(filter,"white_balance",7,false));
       snapshot.Controls.Add(Read(filter,"backlight_compensation",8,false));
       snapshot.Controls.Add(Read(filter,"gain",9,false));
       matches.Add(snapshot);
      }
     } finally { Release(filter); Release(bag); Release(item[0]); item[0]=null; index++; }
    }
    return matches.ToArray();
   } finally { Release(enumerator); Release(system); }
  }
 }
}
'@
$taskMatches = @([BoardVisionUvcDiagnostics.Reader]::Get($DeviceName))
if ($taskMatches.Count -ne 1) { throw "Expected one exact device match, got $($taskMatches.Count)" }
$taskReport = [ordered]@{
    captured_at = [DateTimeOffset]::Now.ToString('o')
    read_only = $true
    flags = '1=automatic, 2=manual; null means unsupported/read failure'
    camera = $taskMatches[0]
}
$taskJson = $taskReport | ConvertTo-Json -Depth 6
if ($OutPath) {
    $taskStream = [System.IO.File]::Open([System.IO.Path]::GetFullPath($OutPath), [System.IO.FileMode]::CreateNew)
    $taskWriter = [System.IO.StreamWriter]::new($taskStream, [System.Text.UTF8Encoding]::new($false))
    try { $taskWriter.Write($taskJson) } finally { $taskWriter.Dispose() }
}
$taskJson
