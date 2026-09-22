<# DirectShow property control without opening/running a capture graph.
   Microsoft IAMVideoProcAmp / IAMCameraControl GetRange, Set, Get.
   Only explicit, range-checked values are changed; every write is read back. #>
param([Parameter(Mandatory=$true)][string]$DeviceName,
      [string]$SettingsBase64 = 'e30=', [switch]$ReadOnly)
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
namespace BoardVisionUvc {
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
 public class Request { public string Name; public int Value, Flags; }
 public class Result {
  public string Name; public int RequestedValue, RequestedFlags, ReadHresult, SetHresult;
  public int? Value, Flags; public bool Verified;
 }
 public class Property {
  public string Name; public int Min, Max, Step, Default, Caps, Value, Flags;
 }
 public static class Controls {
  [DllImport("ole32.dll")]
  static extern int CreateBindCtx(uint reserved, out IBindCtx context);
  public static bool MatchesDevice(string selected, string displayName, string friendlyName) {
   // FFmpeg's dshow alternative name replaces every ':' in GetDisplayName
   // with '_'. Match the full identity; never fall back to a different camera.
   if(selected.StartsWith("@device", StringComparison.OrdinalIgnoreCase))
    return displayName!=null &&
      (String.Equals(displayName,selected,StringComparison.OrdinalIgnoreCase) ||
       String.Equals(displayName.Replace(':','_'),selected,StringComparison.OrdinalIgnoreCase));
   return String.Equals(friendlyName,selected,StringComparison.OrdinalIgnoreCase);
  }
  static void Release(object value) { if(value!=null && Marshal.IsComObject(value)) Marshal.ReleaseComObject(value); }
  static int Id(string name) {
   switch(name) {
    case "exposure": return 4; case "focus": return 6;
    case "brightness": return 0; case "contrast": return 1;
    case "saturation": return 3; case "sharpness": return 4;
    case "white_balance": return 7; case "backlight_compensation": return 8;
    case "gain": return 9;
    default: throw new ArgumentException("Unsupported control: " + name);
   }
  }
  static bool Camera(string name) { return name=="exposure" || name=="focus"; }
  static object FindFilter(string selected) {
   object system=null, found=null; IEnumMoniker enumerator=null; IBindCtx context=null;
   try {
    Marshal.ThrowExceptionForHR(CreateBindCtx(0,out context));
    system=Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("62BE5D10-60EB-11D0-BD3B-00A0C911CE86")));
    Guid category=new Guid("860BB310-5D01-11D0-BD3B-00A0C911CE86");
    if(((ICreateDevEnum)system).CreateClassEnumerator(ref category,out enumerator,0)!=0 || enumerator==null)
     throw new InvalidOperationException("No video input devices");
    var item=new IMoniker[1];
    while(enumerator.Next(1,item,IntPtr.Zero)==0) {
     object bag=null;
     try {
      Guid bagId=typeof(IPropertyBag).GUID; item[0].BindToStorage(null,null,ref bagId,out bag);
      object name; string displayName=null;
      ((IPropertyBag)bag).Read("FriendlyName",out name,IntPtr.Zero);
      if(selected.StartsWith("@device", StringComparison.OrdinalIgnoreCase))
       item[0].GetDisplayName(context,null,out displayName);
      if(MatchesDevice(selected,displayName,name as string)) {
       if(found!=null) throw new InvalidOperationException("Ambiguous device name; no controls changed");
       Guid filterId=new Guid("56A86895-0AD4-11CE-B03A-0020AF0BA770");
       item[0].BindToObject(null,null,ref filterId,out found);
      }
     } finally { Release(bag); Release(item[0]); item[0]=null; }
    }
    if(found==null) throw new InvalidOperationException("Device not found");
    object result=found; found=null; return result;
   } finally { Release(found); Release(enumerator); Release(system); Release(context); }
  }
  public static Property[] Read(string device) {
   object filter=FindFilter(device);
   try {
    var results=new List<Property>();
    foreach(string name in new string[] {"exposure","focus","gain","white_balance","brightness","contrast","saturation","sharpness","backlight_compensation"}) {
     var p=new Property {Name=name}; int id=Id(name), hr;
     try {
      hr=Camera(name) ? ((IAMCameraControl)filter).GetRange(id,out p.Min,out p.Max,out p.Step,out p.Default,out p.Caps)
                      : ((IAMVideoProcAmp)filter).GetRange(id,out p.Min,out p.Max,out p.Step,out p.Default,out p.Caps);
      if(hr<0) continue;
      hr=Camera(name) ? ((IAMCameraControl)filter).Get(id,out p.Value,out p.Flags)
                      : ((IAMVideoProcAmp)filter).Get(id,out p.Value,out p.Flags);
      if(hr>=0) results.Add(p);
     } catch(COMException) { } catch(InvalidCastException) { }
    }
    return results.ToArray();
   } finally { Release(filter); }
  }
  public static Result[] Apply(string device, Request[] requests) {
   object filter=FindFilter(device);
   try {
    // Validate the entire batch before the first write, including supported mode.
    foreach(var request in requests) {
     int min,max,step,def,caps; int id=Id(request.Name);
     int hr=Camera(request.Name) ? ((IAMCameraControl)filter).GetRange(id,out min,out max,out step,out def,out caps)
                                : ((IAMVideoProcAmp)filter).GetRange(id,out min,out max,out step,out def,out caps);
     if(hr<0) Marshal.ThrowExceptionForHR(hr);
     if((request.Flags!=1 && request.Flags!=2) || (caps & request.Flags)==0 ||
        request.Value<min || request.Value>max || (step>0 && (request.Value-min)%step!=0))
      throw new ArgumentException("Invalid value/mode for " + request.Name);
    }
    var results=new List<Result>();
    foreach(var request in requests) {
     int id=Id(request.Name), value=0, flags=0;
     var result=new Result { Name=request.Name, RequestedValue=request.Value, RequestedFlags=request.Flags };
     if(Camera(request.Name)) {
      var api=(IAMCameraControl)filter; result.SetHresult=api.Set(id,request.Value,request.Flags);
      result.ReadHresult=api.Get(id,out value,out flags);
     } else {
      var api=(IAMVideoProcAmp)filter; result.SetHresult=api.Set(id,request.Value,request.Flags);
      result.ReadHresult=api.Get(id,out value,out flags);
     }
     if(result.ReadHresult>=0) { result.Value=value; result.Flags=flags; }
     result.Verified=result.SetHresult>=0 && result.ReadHresult>=0 && flags==request.Flags &&
                      (request.Flags==1 || value==request.Value);
     results.Add(result);
    }
    // A later control can change another property. Verify the final batch,
    // not just the immediate state following each individual Set call.
    foreach(var result in results) {
     int id=Id(result.Name), value=0, flags=0;
     result.ReadHresult=Camera(result.Name) ? ((IAMCameraControl)filter).Get(id,out value,out flags)
                                          : ((IAMVideoProcAmp)filter).Get(id,out value,out flags);
     result.Value=result.ReadHresult>=0 ? (int?)value : null;
     result.Flags=result.ReadHresult>=0 ? (int?)flags : null;
     result.Verified=result.SetHresult>=0 && result.ReadHresult>=0 && flags==result.RequestedFlags &&
                      (result.RequestedFlags==1 || value==result.RequestedValue);
    }
    return results.ToArray();
   } finally { Release(filter); }
  }
 }
}
'@
if ($ReadOnly) {
    [ordered]@{ device_name=$DeviceName; controls=@([BoardVisionUvc.Controls]::Read($DeviceName)) } | ConvertTo-Json -Depth 5 -Compress
    exit 0
}
$settings = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($SettingsBase64)) | ConvertFrom-Json
$requests = @($settings.PSObject.Properties | ForEach-Object {
    $request = [BoardVisionUvc.Request]::new()
    $request.Name = $_.Name
    $request.Value = [int]$_.Value.value
    $request.Flags = [int]$_.Value.flags
    $request
})
$results = @([BoardVisionUvc.Controls]::Apply($DeviceName, $requests))
[ordered]@{ device_name=$DeviceName; controls=$results;
    verified=(@($results | Where-Object { -not $_.Verified }).Count -eq 0)
} | ConvertTo-Json -Depth 5 -Compress
