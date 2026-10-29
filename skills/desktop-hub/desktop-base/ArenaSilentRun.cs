using System;
using System.Diagnostics;
using System.IO;
using System.Text;

namespace ArenaDeskSilentRunner
{
    static class Program
    {
        [STAThread]
        static int Main(string[] args)
        {
            if (args == null || args.Length == 0 || string.IsNullOrWhiteSpace(args[0]))
            {
                return 0;
            }
            try
            {
                string target = args[0];
                bool isLongRunningLoop = false;
                StringBuilder rest = new StringBuilder();
                for (int i = 1; i < args.Length; i++)
                {
                    if (i > 1) rest.Append(' ');
                    string a = args[i] ?? "";
                    if (string.Equals(a, "-Loop", StringComparison.OrdinalIgnoreCase) ||
                        string.Equals(a, "--loop", StringComparison.OrdinalIgnoreCase))
                    {
                        isLongRunningLoop = true;
                    }
                    if (a.IndexOf(' ') >= 0 || a.IndexOf('"') >= 0)
                    {
                        rest.Append('"').Append(a.Replace("\"", "\\\"")).Append('"');
                    }
                    else
                    {
                        rest.Append(a);
                    }
                }

                string fileName;
                string arguments;
                string workDir = Path.GetDirectoryName(Path.GetFullPath(target));

                if (target.EndsWith(".ps1", StringComparison.OrdinalIgnoreCase))
                {
                    string ps = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), @"WindowsPowerShell\v1.0\powershell.exe");
                    if (!File.Exists(ps)) ps = "powershell.exe";
                    fileName = ps;
                    arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File \"" + target + "\"" +
                                (rest.Length > 0 ? " " + rest.ToString() : "");
                }
                else
                {
                    fileName = target;
                    arguments = rest.ToString();
                }

                ProcessStartInfo psi = new ProcessStartInfo(fileName, arguments)
                {
                    CreateNoWindow = true,
                    UseShellExecute = false,
                    WindowStyle = ProcessWindowStyle.Hidden
                };
                if (!string.IsNullOrEmpty(workDir) && Directory.Exists(workDir))
                {
                    psi.WorkingDirectory = workDir;
                }
                using (Process p = Process.Start(psi))
                {
                    if (p != null)
                    {
                        if (isLongRunningLoop)
                        {
                            p.WaitForExit();
                            return p.ExitCode;
                        }
                        p.WaitForExit(60000);
                        return p.HasExited ? p.ExitCode : 0;
                    }
                }
            }
            catch
            {
                return 1;
            }
            return 0;
        }
    }
}
